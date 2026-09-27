"""Daily build: collect Hamburg student postings, describe new ones, publish docs/data/jobs.json.

    python pipeline/build.py                 # full run (AI step only if ANTHROPIC_API_KEY is set)
    python pipeline/build.py --max-ai 50     # cap AI calls this run (default 400)
    python pipeline/build.py --ai-scope all  # AI for every new ad, not only English-friendly ones
    python pipeline/build.py --no-ai

jobs.json is both the published data and the pipeline's memory: postings already in it keep
their extracted facts and are not re-fetched; postings that stop appearing are dropped after
GRACE_DAYS (so one failed source doesn't wipe its jobs off the board)."""
import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import catalog
import extract
import sources
from ai import Enricher

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "jobs.json"
GRACE_DAYS = 3
BUDGETS = {}  # rate-limited sources report their call count in the log
I = re.IGNORECASE


def load_dotenv():
    """Local runs only: read KEY=value lines from a git-ignored .env next to the repo root."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() and not k.lstrip().startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def collect(known):
    tasks = [("Arbeitsagentur", sources.src_arbeitsagentur, (catalog.BA_TERMS, catalog.CITY, catalog.RADIUS_KM)),
             ("Arbeitnow", sources.src_arbeitnow, (catalog.CITY,))]
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if app_id and app_key:
        # first run crawls up to the daily call budget; afterwards only ads from the last 3 days are needed
        first = not any(r["source"] == "Adzuna" for r in known.values())
        budget = sources.CallBudget(catalog.ADZUNA_DAILY_CALLS)
        BUDGETS["Adzuna"] = budget
        tasks.append(("Adzuna", sources.src_adzuna, (catalog.ADZUNA_TERMS, catalog.CITY, catalog.RADIUS_KM, app_id, app_key,
                                                     budget, None if first else 3, 7 if first else 2)))
    else:
        print("  Adzuna           skipped (no ADZUNA_APP_ID / ADZUNA_APP_KEY)")
    for ats, slug, name in catalog.COMPANIES:
        tasks.append((name, sources.ATS[ats], (slug, name, catalog.CITY) if ats == "workday" else (slug, name)))
    jobs, ok, failed = [], set(), []
    with ThreadPoolExecutor(8) as ex:
        futs = {name: ex.submit(fn, *args) for name, fn, args in tasks}
        for name, f in futs.items():
            try:
                got = f.result()
                jobs += got
                ok.add(name)
                calls = f"  ({BUDGETS[name].used} API calls)" if name in BUDGETS else ""
                print(f"  {name:<16} {len(got):>5} postings{calls}")
            except Exception as e:
                failed.append(f"{name}: {type(e).__name__}: {e}")
                print(f"  {name:<16} FAILED ({type(e).__name__})")
    return jobs, ok, failed


def in_area(job):
    # the Arbeitsagentur search is already radius-limited; company feeds list every office worldwide
    return job.source in ("Arbeitsagentur", "Arbeitnow", "Adzuna") or re.search(
        r"hamburg|remote.*(germany|deutschland|dach)|germany.*remote|deutschlandweit", job.location, I)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)|gmbh|se & co\. kg|\bag\b|\bse\b|\bkg\b", "", s.lower()))


def clean_title(title, company):
    """Job-agency titles often start with 'Company name: '. Drop that prefix."""
    head, sep, rest = title.partition(":")
    if sep and rest.strip() and len(head) > 3 and norm(head)[:12] == norm(company)[:12]:
        return rest.strip()
    return title.strip()


def company_key(company):
    words = [w for w in re.findall(r"[a-z0-9äöüß]+", company.lower()) if len(w) > 2 and w not in ("the", "der", "die", "das")]
    return words[0] if words else norm(company)


def describe(job, level, today):
    """Rule-based record for a newly seen posting."""
    text = job.title + "\n" + job.description
    lang = extract.language_of(job.description)
    d = extract.details(job.description)
    feed = job.extra.get("feed", {})
    return {
        "id": job.id, "title": job.title.strip(), "company": job.company.strip(), "location": job.location[:80],
        "url": job.url, "source": job.source, "posted": job.posted or today, "first_seen": today, "last_seen": today,
        "level": level, "field": extract.field_of(job.title), "lang": lang,
        "german": extract.german_of(text, lang), "english": extract.english_of(text, lang),
        "work_mode": job.work_mode or d["work_mode"],
        "hours": d["hours"], "start": d["start"] or feed.get("start", ""), "duration": d["duration"] or feed.get("duration", ""),
        "pay": job.salary or d["pay"], "mandatory": d["mandatory"], "skills": extract.skills_in(text),
    }


def apply_ai(rec, facts):
    rec["ai"] = True
    rec["summary"] = facts["summary"].strip()
    rec["requirements"] = [r.strip() for r in facts["key_requirements"][:5] if r.strip()]
    rec["field"] = facts["field"]
    rec["german_level"] = facts["german_level"]
    rec["english_level"] = facts["english_level"]
    h = facts["hours_per_week"].strip()
    if h:
        rec["hours"] = h if re.search(r"\bh\b|hour|stund", h, I) else f"{h} h/week"
    rec["pay"] = facts["pay"] or rec["pay"]
    rec["mandatory"] = facts["mandatory_internship_only"] or rec["mandatory"]
    rec["student_job"] = facts["is_student_job"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-ai", type=int, default=400)
    ap.add_argument("--ai-scope", choices=["english", "all"], default="english",
                    help="english: only ads not already German-required (~2-3 a day); all: every new ad (~30 a day)")
    ap.add_argument("--no-ai", action="store_true")
    args = ap.parse_args()
    load_dotenv()
    today = date.today().isoformat()

    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"jobs": []}
    known = {j["id"]: j for j in old["jobs"]}

    print(f"{datetime.now():%Y-%m-%d %H:%M} collecting")
    raw, ok_sources, failed = collect(known)

    # keep student-level postings in the area; one record per company+title
    seen_keys, title_owner, fresh, still = {}, {}, [], []
    # on duplicates keep the company's own ad (direct link), then Arbeitnow, then the job agency
    # (Adzuna last: it only returns a snippet of the ad)
    raw.sort(key=lambda j: {"Company Site": 0, "Arbeitnow": 1, "Arbeitsagentur": 2}.get(j.source, 3))
    for job in raw:
        level = extract.level_of(job.title, job.level_hint)
        if not level or not in_area(job):
            continue
        job.title = clean_title(job.title, job.company)
        # same ad often appears twice (job agency + company site, or two legal entities) or once per branch
        # (e.g. one Lidl ad per store): match on the first word of the company name plus the title
        key = company_key(job.company) + "|" + norm(job.title)
        # a long, specific title is the same job even when sources spell the company differently
        # ("HPA - Hamburg Port Authority" / "Hamburg Port Authority AÖR"); short generic titles are not merged
        title_key = "title|" + norm(job.title) if len(norm(job.title)) >= 28 else None
        dup = key if key in seen_keys else title_key if title_key in title_owner else None
        if dup:
            owner = seen_keys[dup] if dup == key else seen_keys[title_owner[title_key]]
            owner[job.source] = owner.get(job.source, 0) + 1
            continue
        seen_keys[key] = {job.source: 1}
        if title_key:
            title_owner[title_key] = key
        job.extra["key"] = key
        (still if job.id in known else fresh).append((job, level))

    def copies(job):  # how many branches posted this ad (largest count within one source)
        return max(seen_keys[job.extra["key"]].values())

    for job, _ in still:
        known[job.id]["last_seen"] = today
        known[job.id]["copies"] = copies(job)
    print(f"{len(raw)} postings -> {len(still) + len(fresh)} student jobs in the area ({len(fresh)} new)")

    enricher = Enricher()
    use_ai = enricher.enabled and not args.no_ai

    def in_scope(rec):
        # "english": only ads the rules don't already mark as German-required - the ones this board is for
        return args.ai_scope == "all" or rec["german"] != "required"
    # older postings the AI never described (key added later, or an earlier call failed) get another try
    retry = [(j, l) for j, l in still if not known[j.id].get("ai") and in_scope(known[j.id])]
    retry = retry[:max(0, args.max_ai - len(fresh))] if use_ai else []
    # one-time backfill: records saved before English detection existed get their ad re-read once
    backfill = [(j, l) for j, l in still if "english" not in known[j.id] and (j, l) not in retry]

    def fetch(item):
        job, _ = item
        if job.fetch and not job.description:
            try:
                job.description = job.fetch()
            except Exception as e:
                failed.append(f"description {job.id}: {e}")
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(fetch, fresh + retry + backfill))
    for job, _ in backfill:
        if job.description:
            rec = known[job.id]
            rec["english"] = extract.english_of(job.title + "\n" + job.description, extract.language_of(job.description))
    new_recs = {job.id: {**describe(job, level, today), "copies": copies(job)} for job, level in fresh}
    texts = {job.id: job.description for job, _ in fresh + retry}

    # AI: new postings first, then the retries
    if use_ai:
        todo = [r for r in new_recs.values() if texts[r["id"]] and in_scope(r)] + [known[j.id] for j, _ in retry if texts[j.id]]
        todo = todo[:args.max_ai]

        def run(rec):
            try:
                apply_ai(rec, enricher.facts(rec["title"], rec["company"], texts[rec["id"]]))
            except Exception as e:
                failed.append(f"ai {rec['id']}: {type(e).__name__}: {e}")
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(run, todo))
        print(f"AI: {sum(1 for r in todo if r.get('ai'))}/{len(todo)} described, "
              f"{enricher.input_tokens:,} in / {enricher.output_tokens:,} out tokens, ~${enricher.cost_usd():.2f}")
    else:
        print("AI: off (no ANTHROPIC_API_KEY or --no-ai)")

    known.update(new_recs)
    # drop postings gone for GRACE_DAYS (only judged when their source actually answered) and AI-flagged non-student jobs
    def alive(r):
        if r.get("student_job") is False:
            return False
        if r["source"] == "Adzuna":  # fetched incrementally, not re-seen daily: expire by age instead
            return (date.fromisoformat(today) - date.fromisoformat(r["posted"])).days <= catalog.ADZUNA_KEEP_DAYS
        source_ok = r["source"] in ok_sources if r["source"] in ("Arbeitsagentur", "Arbeitnow") else r["company"] in ok_sources
        gone_days = (date.fromisoformat(today) - date.fromisoformat(r["last_seen"])).days
        return gone_days < GRACE_DAYS or not source_ok
    jobs = sorted((r for r in known.values() if alive(r)), key=lambda r: (r["posted"], r["id"]), reverse=True)
    # Adzuna copies of an ad we also have from a fuller source (saved before the long-title rule existed,
    # or fetched on a day the other source was down) are dropped at publish time
    for r in jobs:  # older Adzuna records can't be re-read (fetched incrementally): judge by the ad's language
        if r["source"] == "Adzuna" and "english" not in r:
            r["english"] = "required" if r["lang"] == "EN" else "not mentioned"
    fuller = {norm(r["title"]) for r in jobs if r["source"] != "Adzuna" and len(norm(r["title"])) >= 28}
    jobs = [r for r in jobs if not (r["source"] == "Adzuna" and norm(r["title"]) in fuller)]

    if not raw:
        sys.exit("every source failed - keeping the previous jobs.json")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "count": len(jobs),
        "sources": sorted(ok_sources),
        "jobs": jobs,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"published {len(jobs)} jobs -> {OUT.relative_to(ROOT)}")
    if failed:
        print(f"{len(failed)} problems:", *failed[:10], sep="\n  ")


if __name__ == "__main__":
    main()
