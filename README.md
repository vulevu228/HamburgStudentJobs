# Hamburg Student Jobs

**Every Werkstudent, internship, thesis and junior job in Hamburg in one place, updated every morning,
with an honest answer to the question international students ask first: _do I need German?_**

Live site: **https://vulevu228.github.io/HamburgStudentJobs/**

Most job boards show German-only ads to people who searched in English, and hide the language
requirement deep in the text. This board reads every ad and puts the German requirement on the card,
so you can filter to the jobs where English is enough.

## What you can do on the site

- Search by title, company or skill.
- Switch on **English is enough** to hide ads that need good or fluent German.
- Filter by job type (Werkstudent, internship, thesis, junior/trainee), field, work mode and date posted.
- Add your own skills: jobs that ask for them rank higher and the matching skills are highlighted.
- Hide internships that only accept students doing a mandatory internship (Pflichtpraktikum).
- Save jobs; saved jobs and skills stay in your browser only.
- Every filter is kept in the URL, so a search can be shared as a link.
- Visits are counted anonymously with [GoatCounter](https://www.goatcounter.com) (no cookies; only the page
  and the events "open ad" / "save job" are sent, never search terms or skills).

## How it works

```
GitHub Actions (daily, 04:30 UTC)
  pipeline/build.py
    ├─ sources.py   Bundesagentur für Arbeit job search API + career feeds of Hamburg employers
    │               (Greenhouse, Lever, Ashby, SmartRecruiters, Personio, Workday)
    ├─ extract.py   rules: job type, field, ad language, German requirement, skills, hours, pay…
    ├─ ai.py        Claude Haiku 4.5: English summary, key requirements, German/English level
    │               (structured output, each new ad read once)
    └─ docs/data/jobs.json   published data, also the pipeline's memory between runs
  ▼
GitHub Pages: docs/index.html + app.js filter jobs.json in the browser (no server, no cookies)
```

- **Only new ads cost anything, and by default only the ones this board is for.** The AI reads an ad once,
  and only if the rules have not already marked it German-required (about 2-3 new ads a day, well under
  $1 a month). `--ai-scope all` describes every new ad (~30 a day, ~$3 a month); `--max-ai` caps each run.
- **The AI step is optional.** Without an `ANTHROPIC_API_KEY` the rule-based facts are published on their own.
- **Ads that disappear** from their source are removed after 3 days, and only if that source answered
  that day, so one failing source does not empty the board.
- **Duplicates** (the same ad on the job agency and the company's own site) are merged, keeping the
  company's direct link.
- The site shows the title, company, extracted facts and a link to the original ad; the ad text itself
  is not republished.

## Run it yourself

```bash
pip install -r requirements.txt
python pipeline/build.py --no-ai            # rules only
ANTHROPIC_API_KEY=... python pipeline/build.py --max-ai 50
python -m http.server -d docs 8000          # open http://localhost:8000
```

To add an employer, add its career feed to `COMPANIES` in `pipeline/catalog.py`.

## Data sources

- [Bundesagentur für Arbeit, Jobsuche API](https://jobsuche.api.bund.dev/)
- Public job feeds of the employers listed in `pipeline/catalog.py`

AI summaries and language levels can be wrong. Always read the original ad before applying.

## License

Code: MIT. Job ads belong to their publishers.
