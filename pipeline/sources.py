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
    jobs = {}
    for term in terms:
        for page in range(1, max_pages + 1):
            r = get(f"{BA_URL}/v6/jobs", headers=BA_KEY, params={
                "was": term, "wo": city, "umkreis": radius_km, "size": 100, "page": page})
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

                jobs[ref] = Job(f"ba:{ref}", j.get("firma", ""), j["stellenangebotsTitel"], ort,
                                f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}", "Arbeitsagentur",
                                salary=sal, level_hint=j.get("stellenangebotsart", ""), fetch=fetch,
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

            # searchText=<city> already scopes it; locationsText can be "3 Locations"
            loc = j.get("locationsText", "")
            out.append(Job(f"wd:{tenant}:{path.rsplit('_', 1)[-1]}", name, j["title"],
                           loc if city.lower() in loc.lower() else f"{city} ({loc})",
                           f"{base}/{site}{path}", "Company Site", fetch=fetch,
                           posted=workday_date(j.get("postedOn", ""))))
        total = total or d.get("total", 0)  # Workday only reports the total on the first page
        offset += 20
        if offset >= total or not d.get("jobPostings"):
            return out


ATS = {"greenhouse": src_greenhouse, "lever": src_lever, "ashby": src_ashby,
       "smartrecruiters": src_smartrecruiters, "personio": src_personio, "workday": src_workday}


