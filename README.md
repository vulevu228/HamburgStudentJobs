# Hamburg Student Jobs

**Find the student job in Hamburg that fits you.** Every Werkstudent, internship, thesis, side-job and
junior role from the Federal Employment Agency, Adzuna, Arbeitnow, Google for Jobs (JSearch) and company career pages in one place,
updated every morning, and filterable by field, skills, job type and how much German the ad really asks for.
The site is available in English and German.

Live site: **https://hamburgstudentjobs.de/**

## What you can do on the site

- Search by title, company or skill.
- Switch on **English is enough** to hide ads that need good or fluent German.
- Filter by job type (Werkstudent, internship, thesis, junior/trainee), field, work mode and date posted.
- Add your own skills: jobs that ask for them rank higher and the matching skills are highlighted.
- Hide internships that only accept students doing a mandatory internship (Pflichtpraktikum).
- Save jobs; saved jobs and skills stay in your browser only.
- Every filter is kept in the URL, so a search can be shared as a link.
- Switch between English and German at any time (the choice is remembered; `?lang=de` links straight to German).
- Visits are counted anonymously with [GoatCounter](https://www.goatcounter.com) (no cookies; only the page
  and the events "open ad" / "save job" are sent, never search terms or skills).

## How it works

```
GitHub Actions (daily, 04:30 UTC)
  pipeline/build.py
    ├─ sources.py   Bundesagentur für Arbeit job search API, Arbeitnow, Adzuna, JSearch (Google for Jobs)
    │               and the career feeds of 34 Hamburg employers (Greenhouse, Lever, Ashby,
    │               SmartRecruiters, Personio, Workday)
    ├─ extract.py   rules: job type, field, ad language, German requirement, skills, hours, pay…
    ├─ ai.py        Claude Haiku 4.5: English summary, key requirements, German/English level
    │               (structured output, each new ad read once)
    └─ docs/data/jobs.json   published data, also the pipeline's memory between runs
  ▼
GitHub Pages: docs/index.html + app.js filter jobs.json in the browser (no server, no cookies)

Feedback form ──POST──> Azure Function (feedback/) ──> Azure Table Storage, Frankfurt (private)
```

- **Only new ads cost anything, and by default only the ones this board is for.** The AI reads an ad once,
  and only if the rules have not already marked it German-required (about 2-3 new ads a day, well under
  $1 a month). `--ai-scope all` describes every new ad (~30 a day, ~$3 a month); `--max-ai` caps each run.
- **The AI step is optional.** Without an `ANTHROPIC_API_KEY` the rule-based facts are published on their own.
- **Ads that disappear** from their source are removed after 3 days, and only if that source answered
  that day, so one failing source does not empty the board.
- **Duplicates** (the same ad on the job agency and the company's own site, or one ad per branch such as
  a supermarket's 50 stores) are merged into one card, keeping the company's direct link and showing
  "open at N locations".
- The site shows the title, company, extracted facts and a link to the original ad; the ad text itself
  is not republished.
- **Feedback** (questions, ideas, criticism, reports about a job ad) goes to a small Azure Function that
  stores it privately in Table Storage: origin check, bot trap, 5 messages per visitor per day, no IP addresses
  stored, messages deleted after 12 months. Setup: [feedback/SETUP.md](feedback/SETUP.md).

## Run it yourself

```bash
pip install -r requirements.txt
python pipeline/build.py --no-ai            # rules only
ANTHROPIC_API_KEY=... python pipeline/build.py --max-ai 50
python -m http.server -d docs 8000          # open http://localhost:8000
```

To add an employer, add its career feed to `COMPANIES` in `pipeline/catalog.py`.
The link-preview image `docs/og.png` is rendered from `assets/og.html` (1200×630 screenshot).

## Data sources

- [Bundesagentur für Arbeit, Jobsuche API](https://jobsuche.api.bund.dev/)
- [Arbeitnow job board API](https://www.arbeitnow.com/blog/job-board-api)
- [JSearch by OpenWeb Ninja](https://www.openwebninja.com/api/jsearch) (Google for Jobs; free plan, 6 requests a day)
- Public job feeds of the employers listed in `pipeline/catalog.py`

AI summaries and language levels can be wrong. Always read the original ad before applying.

## License

Code: MIT. Job ads belong to their publishers.
