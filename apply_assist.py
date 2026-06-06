"""
JobOracle apply-assist (Stage 4).

Generates a tailored cover letter for a specific job by combining your profile
(headline + experience highlights) with the skills that overlap the job's own
description. Pure Python, deterministic, offline — no LLM call required, so it
runs the same inside the app or the scheduled agent.

The philosophy is semi-automated: this drafts the letter and hands you the apply
link. You review, tweak, and submit. We never auto-submit (ToS + CAPTCHA + ban
risk on a real profile).
"""

from __future__ import annotations
import re
from datetime import datetime
from typing import Dict, List

from scoring import parse_salary, resolve_profile_path


def matched_skills(job: Dict, profile: Dict, limit: int = 8) -> List[str]:
    """Skills from the resume that literally appear in this job's text."""
    blob = f"{job.get('title','')} {job.get('description','')}".lower()
    hits = []
    for sk in profile.get("skills", []):
        if re.search(r"\b" + re.escape(sk.lower()) + r"\b", blob):
            hits.append(sk)
    # de-dupe while preserving order
    seen, out = set(), []
    for s in hits:
        if s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:limit]


def cover_letter(job: Dict, profile: Dict) -> str:
    company = job.get("company", "your team")
    title = job.get("title", "this role")
    skills = matched_skills(job, profile)
    skills_clause = (
        ", ".join(skills[:-1]) + f", and {skills[-1]}"
        if len(skills) > 1 else (skills[0] if skills else "data analytics")
    )
    highlights = profile.get("experience_highlights", [])
    bullets = "\n".join(f"  • {h}" for h in highlights)

    # Pull a single most-relevant hook line from the job description
    desc = job.get("description", "")
    hook = ""
    for sentence in re.split(r"(?<=[.!?])\s+|;\s+", desc):
        s = sentence.strip()
        if 25 <= len(s) <= 130 and any(
            k in s.lower() for k in ("sql", "python", "etl", "pyspark", "dashboard", "machine learning", "analytics")
        ):
            hook = s
            break

    today = datetime.now().strftime("%B %d, %Y")
    letter = f"""{today}

Dear {company} Hiring Team,

I'm excited to apply for the {title} role at {company}. {profile.get('headline','')}

What drew me to this position is the overlap between what you're building and the
work I do every day. Your description emphasizes {skills_clause} — all core to my
toolkit. {("Specifically, the focus on “" + hook + "” maps directly to my experience.") if hook else ""}

A few things I'd bring to {company}:
{bullets}

I'd welcome the chance to discuss how I can help {company} turn data into faster,
better decisions. Thank you for your consideration.

Best regards,
{profile.get('name','')}
{profile.get('contact_line','')}
"""
    return letter.strip() + "\n"


def application_kit(job: Dict, profile: Dict) -> Dict:
    """Everything you need to apply, bundled."""
    sal = parse_salary(job.get("comp_raw", ""))
    return {
        "title": job.get("title"),
        "company": job.get("company"),
        "apply_url": job.get("url"),
        "matched_skills": matched_skills(job, profile),
        "salary": sal,
        "cover_letter": cover_letter(job, profile),
    }


if __name__ == "__main__":
    import json, pathlib

    here = pathlib.Path(__file__).parent
    profile = json.loads(resolve_profile_path(here / "data").read_text())
    jobs = json.loads((here / "data" / "jobs.json").read_text())["jobs"]
    # demo: cover letter for the top enriched job (Afresh / Misch)
    target = next(j for j in jobs if j["company"] == "Afresh")
    print(cover_letter(target, profile))
