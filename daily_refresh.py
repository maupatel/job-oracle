"""
JobOracle daily refresh (Stage 3 helper).

The scheduled agent fetches fresh Indeed listings via the MCP search tool and
dumps the raw markdown into data/incoming.txt. This script then:

    1. parses that markdown into structured job records
    2. dedupes
    3. scores every job against your resume (scoring.py)
    4. diffs against data/seen.json to find NEW jobs since last run
    5. rewrites data/jobs.json (so the app shows today's listings)
    6. writes data/email_body.txt — a short, scannable digest of new high-fit jobs

Keeping the parse/score/diff logic here (not in the agent prompt) makes each
scheduled run deterministic and cheap.

Usage:  python daily_refresh.py [incoming.txt] [--threshold 75]
"""

from __future__ import annotations
import json
import pathlib
import re
import sys
from datetime import datetime

from scoring import score_all, parse_salary, resolve_profile_path

HERE = pathlib.Path(__file__).parent
DATA = HERE / "data"

JOB_TYPE_MAP = {
    "full-time": "fulltime", "part-time": "parttime", "contract": "contract",
    "temporary": "temporary", "internship": "internship",
}


def _field(block: str, label: str) -> str:
    m = re.search(rf"\*\*{re.escape(label)}:\*\*\s*(.+)", block)
    return m.group(1).strip() if m else ""


def parse_incoming(text: str) -> list[dict]:
    """Parse the markdown emitted by the Indeed search_jobs tool."""
    jobs = []
    # split on each Job Title marker
    blocks = re.split(r"(?=\*\*Job Title:\*\*)", text)
    for b in blocks:
        if "**Job Title:**" not in b:
            continue
        title = _field(b, "Job Title")
        if not title:
            continue
        jt_raw = _field(b, "Job Type").lower()
        jobs.append({
            "id": _field(b, "Job Id") or title,
            "title": title,
            "company": _field(b, "Company"),
            "location": _field(b, "Location"),
            "job_type": JOB_TYPE_MAP.get(jt_raw, ""),
            "posted": _field(b, "Posted on"),
            "comp_raw": _field(b, "Compensation"),
            "url": _field(b, "View Job URL"),
            "query": "",
            "description": "",
        })
    return jobs


def dedupe(jobs: list[dict]) -> list[dict]:
    seen, out = set(), []
    for j in jobs:
        key = (j["title"].lower(), j["company"].lower(), j["location"].lower())
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out


def job_key(j: dict) -> str:
    return f"{j['company'].lower()}|{j['title'].lower()}"


def load_seen() -> set:
    f = DATA / "seen.json"
    if f.exists():
        return set(json.loads(f.read_text()).get("keys", []))
    return set()


def save_seen(keys: set):
    (DATA / "seen.json").write_text(json.dumps({"keys": sorted(keys)}, indent=2))


def fmt_money(sal: dict) -> str:
    if not sal["known"]:
        return "salary n/a"
    return f"${sal['min']/1000:.0f}k-${sal['max']/1000:.0f}k"


def main():
    args = [a for a in sys.argv[1:]]
    threshold = 75
    if "--threshold" in args:
        i = args.index("--threshold")
        threshold = int(args[i + 1])
        del args[i:i + 2]
    incoming = pathlib.Path(args[0]) if args else (DATA / "incoming.txt")

    profile = json.loads(resolve_profile_path(DATA).read_text())

    if not incoming.exists():
        print(f"No incoming file at {incoming}; nothing to do.")
        return

    jobs = dedupe(parse_incoming(incoming.read_text(encoding="utf-8")))
    if not jobs:
        print("Parsed 0 jobs from incoming file.")
        return

    scored = score_all(jobs, profile)

    # diff against what we've already seen
    seen = load_seen()
    new_jobs = [j for j in scored if job_key(j) not in seen and j["score"] >= threshold]

    # persist today's full listing for the app
    (DATA / "jobs.json").write_text(json.dumps(
        {"fetched_at": datetime.now().strftime("%Y-%m-%d"),
         "source": "Indeed", "jobs": jobs}, indent=2), encoding="utf-8")

    # mark everything fetched as seen
    save_seen(seen | {job_key(j) for j in scored})

    # build short email digest
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"JobOracle — {len(new_jobs)} new matches (fit >= {threshold}) · {today}", ""]
    if not new_jobs:
        lines.append("No new high-fit matches today.")
    else:
        for j in new_jobs:
            lines.append(
                f"[{j['score']}] {j['title']} — {j['company']} · "
                f"{fmt_money(j['salary'])} · {j['location']} · {j['url']}"
            )
    body = "\n".join(lines) + "\n"
    (DATA / "email_body.txt").write_text(body, encoding="utf-8")
    print(body)


if __name__ == "__main__":
    main()
