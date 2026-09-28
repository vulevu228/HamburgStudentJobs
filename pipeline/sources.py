"""Fetchers for every job source. Each returns a list of Job; descriptions that need an extra
request are fetched lazily through Job.fetch so only postings that survive the cheap filters cost a call."""
import base64
import html
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import requests

UA = {"User-Agent": "Mozilla/5.0 (HamburgStudentJobs; +https://github.com/vulevu228/HamburgStudentJobs)"}
BA_KEY = {"X-API-Key": "jobboerse-jobsuche", **UA}
BA_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc"
I = re.IGNORECASE


@dataclass
class Job:
    id: str                 # "<source>:<native id>", stable across runs
    company: str
    title: str
    location: str
    url: str
    source: str             # tracker "Source" value
    work_mode: str = ""
    salary: str = ""
    level_hint: str = ""    # extra text used for level detection (employment type etc.)
    fetch: object = None    # callable returning the description, run only for survivors
    posted: str = ""        # YYYY-MM-DD first published, when the source says
    description: str = ""
    extra: dict = field(default_factory=dict)


def get(url, headers=UA, **kw):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=25, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def ms_date(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat() if ms else ""


def workday_date(text):
    """'Posted Today' / 'Posted Yesterday' / 'Posted 3 Days Ago' / 'Posted 30+ Days Ago' -> ISO date."""
    t = text.lower()
    days = 0 if "today" in t else 1 if "yesterday" in t else int(m.group(1)) if (m := re.search(r"(\d+)", t)) else None
    return (date.today() - timedelta(days=days)).isoformat() if days is not None else ""


def strip_html(s):
    s = html.unescape(s or "")
    s = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", s, flags=I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[ \t\xa0]+", " ", html.unescape(s)).strip()


# ---------------------------------------------------------------- sources
def src_arbeitsagentur(terms, city, radius_km, max_pages=10):
    """terms: search words, or dicts of extra query parameters (e.g. a job category without a keyword)."""
    jobs = {}
    for term in terms:
        query = term if isinstance(term, dict) else {"was": term}
        for page in range(1, max_pages + 1):
            r = get(f"{BA_URL}/v6/jobs", headers=BA_KEY, params={
                **query, "wo": city, "umkreis": radius_km, "size": 100, "page": page})
            batch = r.json().get("ergebnisliste", [])
            for j in batch:
                ref = j["referenznummer"]
                # apprenticeships (Ausbildung) are not student jobs and come without a title
                if ref in jobs or j.get("stellenangebotsart") == "AUSBILDUNG" or not j.get("stellenangebotsTitel"):
                    continue
                locs = j.get("stellenlokationen") or [{}]
                ort = (locs[0].get("adresse") or {}).get("ort", "")
                sal = ""
                if j.get("gehaltsspanneVon"):
                    unit = "EUR/h" if j.get("verguetungsangabe") == "STUNDENLOHN" else "EUR"
                    sal = f'{j["gehaltsspanneVon"]:g}-{j.get("gehaltsspanneBis", j["gehaltsspanneVon"]):g} {unit}'

                def fetch(ref=ref):
                    b = base64.b64encode(ref.encode()).decode()
                    d = get(f"{BA_URL}/v4/jobdetails/{b}", headers=BA_KEY).json()
                    return d.get("stellenangebotsBeschreibung", "")

                # the agency's type is only a usable hint next to a matching keyword; a category-only hit
                # (volunteer service, social workers, shop staff filed as "internship") must say it in the title
                hint = j.get("stellenangebotsart", "") if "was" in query else ""
                jobs[ref] = Job(f"ba:{ref}", j.get("firma", ""), j["stellenangebotsTitel"], ort,
                                f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}", "Arbeitsagentur",
                                salary=sal, level_hint=hint, fetch=fetch,
                                posted=j.get("datumErsteVeroeffentlichung", "")[:10])
                feed = jobs[ref].extra.setdefault("feed", {})  # structured facts the ad text often omits
                if (j.get("eintrittszeitraum") or {}).get("von"):
                    feed["start"] = j["eintrittszeitraum"]["von"]
                if j.get("befristungInMonaten"):
                    feed["duration"] = f'{j["befristungInMonaten"]} months'
                if j.get("arbeitszeitTeilzeitVormittag") or j.get("arbeitszeitTeilzeitNachmittag"):
                    feed["hours"] = "part-time"
            if len(batch) < 100:
                break
    return list(jobs.values())


def src_greenhouse(slug, name):
    data = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"}).json()
    return [Job(f"gh:{slug}:{j['id']}", name, j["title"], (j.get("location") or {}).get("name", ""),
                j["absolute_url"], "Company Site", description=strip_html(j.get("content", "")),
                posted=(j.get("first_published") or j.get("updated_at") or "")[:10])
            for j in data.get("jobs", [])]


def src_lever(slug, name):
    out = []
    for j in get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}).json():
        cat = j.get("categories", {})
        desc = j.get("descriptionPlain", "") + "\n" + "\n".join(
            l.get("text", "") + "\n" + strip_html(l.get("content", "")) for l in j.get("lists", []))
        out.append(Job(f"lever:{slug}:{j['id']}", name, j["text"],
                       " / ".join(filter(None, [cat.get("location")] + cat.get("allLocations", []))),
                       j["hostedUrl"], "Company Site", work_mode=(j.get("workplaceType") or "").title(),
                       level_hint=cat.get("commitment", ""), description=desc,
                       posted=ms_date(j.get("createdAt"))))
    return out


def src_ashby(slug, name):
    data = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", params={"includeCompensation": "true"}).json()
    out = []
    for j in data.get("jobs", []):
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations", [])]
        mode = {"OnSite": "Onsite", "Hybrid": "Hybrid", "Remote": "Remote"}.get(j.get("workplaceType") or "", "")
        out.append(Job(f"ashby:{slug}:{j['id']}", name, j["title"], " / ".join(filter(None, locs)), j["jobUrl"],
                       "Company Site", work_mode=mode, level_hint=j.get("employmentType", ""),
                       salary=(j.get("compensation") or {}).get("compensationTierSummary", "") or "",
                       description=j.get("descriptionPlain", ""), posted=(j.get("publishedAt") or "")[:10]))
    return out


def src_smartrecruiters(slug, name):
    out, offset = [], 0
    while True:
        d = get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                params={"limit": 100, "offset": offset}).json()
        for j in d.get("content", []):
            loc = j.get("location", {})
            mode = "Remote" if loc.get("remote") else "Hybrid" if loc.get("hybrid") else ""

            def fetch(pid=j["id"]):
                p = get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{pid}").json()
                secs = (p.get("jobAd") or {}).get("sections", {})
                return "\n".join(strip_html(s.get("text", "")) for s in secs.values() if isinstance(s, dict))

            out.append(Job(f"sr:{slug}:{j['id']}", name, j["name"], loc.get("fullLocation", ""),
                           f"https://jobs.smartrecruiters.com/{slug}/{j['id']}", "Company Site", work_mode=mode,
                           level_hint=(j.get("typeOfEmployment") or {}).get("label", ""), fetch=fetch,
                           posted=(j.get("releasedDate") or "")[:10]))
        offset += 100
        if offset >= d.get("totalFound", 0):
            return out


def src_personio(slug, name):
    root = ET.fromstring(get(f"https://{slug}.jobs.personio.de/xml").content)
    out = []
    for p in root.iter("position"):
        t = lambda tag: (p.findtext(tag) or "").strip()
        offices = [t("office")] + [o.text or "" for o in p.iter("additionalOffice")]
        desc = "\n".join(strip_html(d.findtext("value")) for d in p.iter("jobDescription"))
        out.append(Job(f"personio:{slug}:{t('id')}", name, t("name"), " / ".join(filter(None, offices)),
                       f"https://{slug}.jobs.personio.de/job/{t('id')}", "Company Site",
                       level_hint=t("employmentType") + " " + t("schedule"), description=desc,
                       posted=t("createdAt")[:10]))
    return out


def src_workday(spec, name, city):
    tenant, dc, site = spec.split("|")
    base = f"https://{tenant}.{dc}.myworkdayjobs.com"
    out, offset, total = [], 0, None
    while True:
        d = requests.post(f"{base}/wday/cxs/{tenant}/{site}/jobs", headers=UA, timeout=25,
                          json={"limit": 20, "offset": offset, "searchText": city, "appliedFacets": {}}).json()
        for j in d.get("jobPostings", []):
            path = j["externalPath"]

            def fetch(path=path):
                info = get(f"{base}/wday/cxs/{tenant}/{site}{path}").json().get("jobPostingInfo", {})
                return strip_html(info.get("jobDescription", "")) + "\nLocation: " + info.get("location", "")

            # searchText=<city> also matches ad text, so keep only ads placed in the city or at several
            # locations ("3 Locations", which usually includes it)
            loc = j.get("locationsText", "")
            if city.lower() not in loc.lower() and not re.search(r"\d+ locations", loc, I):
                continue
            out.append(Job(f"wd:{tenant}:{path.rsplit('_', 1)[-1]}", name, j["title"],
                           loc if city.lower() in loc.lower() else f"{city} ({loc})",
                           f"{base}/{site}{path}", "Company Site", fetch=fetch,
                           posted=workday_date(j.get("postedOn", ""))))
        total = total or d.get("total", 0)  # Workday only reports the total on the first page
        offset += 20
        if offset >= total or not d.get("jobPostings"):
            return out


def src_arbeitnow(city, max_pages=60):
    """Arbeitnow's free job-board API (Germany-wide, many English ads). Paged, behind Cloudflare, so it is
    paced and backs off on 429. Keeps jobs in the city plus remote jobs."""
    out, url, page, waits = [], "https://www.arbeitnow.com/api/job-board-api", 0, 0
    while url and page < max_pages:
        r = requests.get(url, headers={**UA, "Accept": "application/json"}, timeout=30)
        if r.status_code == 429 or not r.text.lstrip().startswith("{"):
            waits += 1
            if waits > 6:
                raise RuntimeError(f"rate-limited on page {page + 1}")
            time.sleep(15 * waits)
            continue
        r.raise_for_status()
        d = r.json()
        for j in d.get("data", []):
            loc = j.get("location", "")
            if city.lower() not in loc.lower() and not j.get("remote"):
                continue
            out.append(Job(f"arbeitnow:{j['slug']}", j.get("company_name", ""), j["title"],
                           loc if city.lower() in loc.lower() else f"Remote, Germany ({loc})",
                           j["url"], "Arbeitnow", work_mode="Remote" if j.get("remote") else "",
                           level_hint=" ".join(j.get("job_types", [])), description=strip_html(j.get("description", "")),
                           posted=datetime.fromtimestamp(j["created_at"], timezone.utc).date().isoformat() if j.get("created_at") else ""))
        url = (d.get("links") or {}).get("next")
        page += 1
        time.sleep(1.5)
    return out


class CallBudget:
    """Adzuna's free plan: 25 calls/min, 250/day, 2,500/month. Every call goes through here."""
    def __init__(self, limit):
        self.limit, self.used = limit, 0

    def take(self):
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


def src_adzuna(terms, city, radius_km, app_id, app_key, budget, max_days_old=None, max_pages=5):
    """Adzuna job search (Germany). Only a ~500-character description snippet comes back.
    The first run crawls everything within `budget`; later runs pass max_days_old to fetch only new ads."""
    out, seen = [], set()
    for term in terms:
        page = 1
        while page <= max_pages and budget.take():
            params = {"app_id": app_id, "app_key": app_key, "what": term, "where": city, "distance": radius_km,
                      "results_per_page": 50, "sort_by": "date", "content-type": "application/json"}
            if max_days_old:
                params["max_days_old"] = max_days_old
            r = requests.get(f"https://api.adzuna.com/v1/api/jobs/de/search/{page}", params=params, headers=UA, timeout=30)
            if r.status_code in (401, 403):
                raise RuntimeError(f"Adzuna rejected the credentials (HTTP {r.status_code})")
            r.raise_for_status()
            results = r.json().get("results", [])
            for j in results:
                jid = str(j["id"])
                if jid in seen:
                    continue
                seen.add(jid)
                sal = ""
                if j.get("salary_min") and str(j.get("salary_is_predicted")) != "1":  # predicted salaries need extra labelling
                    lo, hi = j["salary_min"], j.get("salary_max") or j["salary_min"]
                    sal = f"{lo:,.0f}-{hi:,.0f} EUR/yr" if lo > 1000 else f"{lo:g}-{hi:g} EUR/h"
                out.append(Job(f"adzuna:{jid}", (j.get("company") or {}).get("display_name", ""), strip_html(j.get("title", "")),
                               (j.get("location") or {}).get("display_name", city), j["redirect_url"], "Adzuna",
                               salary=sal, level_hint=j.get("contract_time") or "",
                               description=strip_html(j.get("description", "")), posted=(j.get("created") or "")[:10]))
            time.sleep(2.6)  # stay under 25 calls per minute
            if len(results) < 50:
                break
            page += 1
    return out


def src_jsearch(queries, city, api_key, budget, date_posted="3days"):
    """JSearch (OpenWeb Ninja): Google for Jobs results, i.e. ads from LinkedIn, StepStone, Indeed and
    company sites. Free plan: 200 requests/month, hard limit - one request per query (10 ads), never paged."""
    # the same API is sold directly and through RapidAPI, with different addresses and key headers;
    # a key from either works: on a refusal the other one is tried (refused calls cost no quota)
    providers = [("OpenWeb Ninja", "https://api.openwebninja.com/jsearch/search", {"x-api-key": api_key}),
                 ("RapidAPI", "https://jsearch.p.rapidapi.com/search",
                  {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})]
    out, seen, refused = [], set(), []
    for q in queries:
        if not budget.take():
            break
        while True:
            name, url, auth = providers[0]
            r = requests.get(url, headers={**UA, **auth}, timeout=40,
                             params={"query": q, "country": "de", "date_posted": date_posted, "num_pages": 1})
            if r.status_code not in (401, 403):
                break
            refused.append(f"{name} HTTP {r.status_code}")
            providers.pop(0)
            if not providers:
                raise RuntimeError(f"JSearch rejected the key ({', '.join(refused)})")
        if r.status_code == 429:
            raise RuntimeError("JSearch quota used up for this month (HTTP 429)")
        r.raise_for_status()
        data = r.json().get("data") or []
        for j in data.get("jobs", []) if isinstance(data, dict) else data:
            if not j.get("job_id") or j["job_id"] in seen:
                continue
            seen.add(j["job_id"])
            place = j.get("job_location") or j.get("job_city") or ""
            remote = bool(j.get("job_is_remote"))
            if city.lower() not in f"{place} {j.get('job_city') or ''}".lower():
                if not (remote and (j.get("job_country") or "").upper() == "DE"):
                    continue
                place = f"Remote, Germany ({place or 'Germany'})"
            # prefer the employer's own apply link over a job board's
            direct = next((o for o in j.get("apply_options") or [] if o.get("is_direct")), None)
            url = (direct or {}).get("apply_link") or j.get("job_apply_link") or j.get("job_google_link")
            via = (direct or {}).get("publisher") or j.get("job_publisher") or ""
            sal = ""
            if j.get("job_min_salary") and (j.get("job_salary_currency") or "EUR") == "EUR":
                lo, hi = j["job_min_salary"], j.get("job_max_salary") or j["job_min_salary"]
                period = (j.get("job_salary_period") or "").upper()
                sal = f"{lo:g}-{hi:g} EUR/h" if period == "HOUR" else f"{lo:,.0f}-{hi:,.0f} EUR/yr" if period == "YEAR" else ""
            job = Job(f"jsearch:{j['job_id']}", j.get("employer_name") or "", j.get("job_title") or "", place, url, "JSearch",
                      work_mode="Remote" if remote else "", salary=sal,
                      level_hint=" ".join(j.get("job_employment_types") or []).replace("INTERN", "internship"),
                      description=strip_html(j.get("job_description") or ""),
                      posted=(j.get("job_posted_at_datetime_utc") or "")[:10])
            job.extra["via"] = via
            out.append(job)
        time.sleep(1)
    return out


ATS = {"greenhouse": src_greenhouse, "lever": src_lever, "ashby": src_ashby,
       "smartrecruiters": src_smartrecruiters, "personio": src_personio, "workday": src_workday}


