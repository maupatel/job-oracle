# 🧭 JobOracle

A local job-search command center for a Senior Data Analyst / Data Engineer job hunt.
Pulls live Indeed listings, scores each against your resume, and tracks your
applications — all running on your machine, free, no accounts.

## What it does (Stage 1 — done)
- **Aggregate**: live jobs across your 4 target titles (Senior Data Analyst,
  Data Engineer, Business Analyst, BI Analyst), deduped.
- **Match**: a transparent 0–100 fit score per job (title + pay + type + skills),
  with a plain-English "why" for each. Filters for score, remote, salary floor,
  full-time, keyword.
- **Track**: Saved → Applied → Interviewing → Offer / Rejected board with notes,
  saved to `data/applications.json`.

## Run it locally
```
cd C:\job-oracle
pip install -r requirements.txt
cp data/profile.example.json data/profile.json   # then edit with your details
streamlit run app.py
```
Then open the URL Streamlit prints (default http://localhost:8501).
If you don't create `data/profile.json`, the app falls back to the example template.

## Push to GitHub
```
cd C:\job-oracle
git init && git add -A && git commit -m "JobOracle: aggregate + match + apply + daily digest"
git branch -M main
git remote add origin https://github.com/<you>/job-oracle.git
git push -u origin main
```
Your personal `data/profile.json`, tracker, and runtime files are git-ignored.

## Deploying it online (Streamlit Community Cloud — free)
1. Push this repo to GitHub (see below).
2. Go to https://share.streamlit.io → "New app" → pick this repo, branch `main`,
   main file `app.py`. It installs `requirements.txt` and gives you a public URL.
3. Every `git push` auto-redeploys — that's the iterative loop.

**Important caveat:** a deployed app cannot call the Indeed MCP tools (those only
exist inside Claude). So the public demo shows the committed snapshot in
`data/jobs.json` and won't self-refresh. To make a *truly live* public site,
swap the data engine for a server-callable public jobs API (e.g. Adzuna free
tier or Remotive) — see "Making it live for everyone" below.

## Making it live for everyone (future)
The scoring, tracker, and apply-assist are already source-agnostic. To go fully
public + auto-refreshing:
- Replace the fetch step with a real API the server can call itself:
  **Adzuna** (free app_id/app_key, broad coverage) or **Remotive** (no key,
  remote-only). Write a `fetch_<source>.py` that returns the same job records and
  feeds `daily_refresh.py`.
- Let each visitor paste/upload their own resume instead of a hardcoded profile.
- Store API keys in Streamlit secrets, not in the repo.

## How the data gets there (local)
This app does **not** scrape the web itself. The data engine (Claude in this
environment, using the Indeed MCP tools) writes `data/jobs.json`. To refresh the
listings, ask Claude to "refresh JobOracle jobs" — it re-runs the searches and
rewrites that file. Stage 3 automates this as a daily scheduled task.

## Files
| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI (Matches + Apply-assist + Tracker tabs) |
| `scoring.py` | Pure-Python fit-score engine (unit-testable) |
| `apply_assist.py` | Tailored cover-letter generator (Stage 4) |
| `daily_refresh.py` | Parses fetched listings, scores, diffs, writes email digest (Stage 3) |
| `data/profile.json` | Your resume skills + preferences (edit to tune scoring) |
| `data/jobs.json` | Live job listings (refreshed by the agent) |
| `data/applications.json` | Your tracker board (written by the app) |
| `data/seen.json` | Jobs already emailed (so the digest only shows new ones) |

## Tuning the scoring
Edit `data/profile.json`:
- `min_salary` — your floor (default 120000)
- `target_titles` / `title_keywords` — what counts as on-target
- `skills` — resume keywords matched against job titles/descriptions

`python scoring.py` prints the top-10 ranked jobs as a quick sanity check.

## Stages
- **Stage 1 — Aggregate + Match + Track**: DONE.
- **Stage 3 — Daily email agent**: DONE. Scheduled task `joboracle-daily-matches`
  runs weekdays 8 AM CT: refetches Indeed, scores, and emails new matches with
  fit >= 75. Tip: click **Run now** on the task once to pre-approve its tools
  (Indeed search + Gmail send) so future runs don't pause on prompts.
- **Stage 4 — Apply-assist**: DONE. "✍️ Apply-assist" tab drafts a tailored
  cover letter from your highlights + the job's overlapping skills. You edit,
  download, open the apply link, and submit. No auto-submit by design (ToS +
  CAPTCHA + ban risk).

### Possible next steps
- Richer tracker: follow-up reminders and date tracking.
- Company intel: pull Indeed reviews/salary (`get_company_data`) into each card.
- Search your local metro in addition to remote.
