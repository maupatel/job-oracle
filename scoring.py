"""
JobOracle scoring engine.

Pure functions, no I/O, no Streamlit — so it can be unit-tested and reused by
both the app and the (future) scheduled daily agent.

A job gets a 0-100 fit score built from four transparent components:
    title_fit   (0-40)  how well the title matches your target roles + seniority
    pay_fit     (0-30)  parsed salary vs. your minimum
    type_fit    (0-15)  full-time + remote preferences
    skills_fit  (0-15)  resume skill keywords found in title/description

Each component also emits a short reason string so the UI can explain *why*.
"""

from __future__ import annotations
import pathlib
import re
from typing import Dict, List, Tuple

HOURS_PER_YEAR = 2080  # 40h/wk * 52wk — used to annualize hourly pay


def resolve_profile_path(data_dir) -> pathlib.Path:
    """Prefer the user's personal profile.json; fall back to the committed
    profile.example.json (used on a fresh clone or public deploy)."""
    data_dir = pathlib.Path(data_dir)
    personal = data_dir / "profile.json"
    return personal if personal.exists() else data_dir / "profile.example.json"


# --------------------------------------------------------------------------- #
# Salary parsing
# --------------------------------------------------------------------------- #
def parse_salary(comp_raw: str) -> Dict:
    """
    Turn a raw Indeed compensation string into a normalized annual range.

    Handles:
        "$120,000 - $170,000 a year"
        "$80 - $90 an hour"
        "$124,190.00 - $178,861.94 a year"
        "N/A" / "" -> unknown
    Returns dict: {min, max, mid, period, known}  (min/max/mid annualized USD)
    """
    if not comp_raw or comp_raw.strip().upper() in ("N/A", "NA", "NONE"):
        return {"min": None, "max": None, "mid": None, "period": None, "known": False}

    text = comp_raw.lower()
    hourly = "hour" in text
    nums = re.findall(r"[\d,]+(?:\.\d+)?", comp_raw)
    vals = []
    for n in nums:
        try:
            vals.append(float(n.replace(",", "")))
        except ValueError:
            continue
    if not vals:
        return {"min": None, "max": None, "mid": None, "period": None, "known": False}

    lo, hi = min(vals), max(vals)
    if hourly:
        lo *= HOURS_PER_YEAR
        hi *= HOURS_PER_YEAR
    return {
        "min": lo,
        "max": hi,
        "mid": (lo + hi) / 2,
        "period": "hour" if hourly else "year",
        "known": True,
    }


# --------------------------------------------------------------------------- #
# Component scorers — each returns (points, reason)
# --------------------------------------------------------------------------- #
def _title_fit(title: str, profile: Dict) -> Tuple[float, str]:
    t = title.lower()
    pts = 0.0
    matched = [kw for kw in profile.get("title_keywords", []) if kw in t]
    if matched:
        pts += 28
        reason = f"Title matches {matched[0]}"
    else:
        reason = "Title is off-target"
    # downrank clear noise
    if "ai trainer" in t or "annotation" in t:
        pts -= 18
        reason = "Looks like gig/AI-trainer work, not a staff role"
    if "director" in t or "manager" in t or "head of" in t:
        pts -= 6
        reason += "; more senior/managerial than target"
    # seniority bonus
    if any(sk in t for sk in profile.get("seniority_keywords", [])):
        pts += 12
        reason += "; senior-level"
    return max(0.0, min(40.0, pts)), reason


def _pay_fit(sal: Dict, profile: Dict) -> Tuple[float, str]:
    floor = profile.get("min_salary", 0)
    if not sal["known"]:
        return 15.0, "Salary not listed (neutral)"
    mid = sal["mid"]
    if mid >= floor * 1.25:
        return 30.0, f"Pay ~${mid/1000:.0f}k — well above your ${floor/1000:.0f}k floor"
    if mid >= floor:
        return 24.0, f"Pay ~${mid/1000:.0f}k — clears your ${floor/1000:.0f}k floor"
    if sal["max"] and sal["max"] >= floor:
        return 12.0, f"Top of range (${sal['max']/1000:.0f}k) reaches your floor, midpoint below"
    return 0.0, f"Pay ~${mid/1000:.0f}k — below your ${floor/1000:.0f}k floor"


def _type_fit(job: Dict, profile: Dict) -> Tuple[float, str]:
    pts = 0.0
    bits = []
    jt = (job.get("job_type") or "").lower()
    if jt == "fulltime":
        pts += 9
        bits.append("full-time")
    elif jt in ("parttime", "contract", "temporary", "internship"):
        pts += 2
        bits.append(jt)
    else:
        pts += 5  # unknown, don't punish
    loc = (job.get("location") or "").lower()
    title = (job.get("title") or "").lower()
    if "remote" in loc or "remote" in title:
        pts += 6
        bits.append("remote")
    reason = "Good fit: " + ", ".join(bits) if bits else "Type/location unknown"
    return min(15.0, pts), reason


def _skills_fit(job: Dict, profile: Dict) -> Tuple[float, str]:
    blob = f"{job.get('title','')} {job.get('description','')}".lower()
    hits = []
    for sk in profile.get("skills", []):
        # word-ish boundary match to avoid 'r' / 'sas' false hits
        if re.search(r"\b" + re.escape(sk.lower()) + r"\b", blob):
            hits.append(sk)
    if not hits:
        return 6.0, "No resume skills detected in title (enrich w/ full description for more)"
    pts = min(15.0, 4.0 + 2.5 * len(hits))
    shown = ", ".join(hits[:5])
    return pts, f"Matches your skills: {shown}"


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def score_job(job: Dict, profile: Dict) -> Dict:
    """Return job enriched with score, salary, component breakdown and reasons."""
    sal = parse_salary(job.get("comp_raw", ""))
    title_p, title_r = _title_fit(job.get("title", ""), profile)
    pay_p, pay_r = _pay_fit(sal, profile)
    type_p, type_r = _type_fit(job, profile)
    skills_p, skills_r = _skills_fit(job, profile)
    total = round(title_p + pay_p + type_p + skills_p)

    enriched = dict(job)
    enriched.update(
        {
            "salary": sal,
            "score": total,
            "components": {
                "title": round(title_p, 1),
                "pay": round(pay_p, 1),
                "type": round(type_p, 1),
                "skills": round(skills_p, 1),
            },
            "reasons": [title_r, pay_r, type_r, skills_r],
        }
    )
    return enriched


def score_all(jobs: List[Dict], profile: Dict) -> List[Dict]:
    scored = [score_job(j, profile) for j in jobs]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


if __name__ == "__main__":
    # tiny smoke test
    import json, pathlib

    here = pathlib.Path(__file__).parent
    profile = json.loads(resolve_profile_path(here / "data").read_text())
    jobs = json.loads((here / "data" / "jobs.json").read_text())["jobs"]
    for j in score_all(jobs, profile)[:10]:
        print(f"{j['score']:>3}  {j['title'][:42]:42}  {j['company']}")
