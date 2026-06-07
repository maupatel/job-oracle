"""
JobOracle apply-assist.

Generates a tailored cover letter for a specific job by combining the user's
profile (headline + experience highlights + resume skills) with the skills and
language that overlap the job's own description.

Design rules requested by the user:
  - NO dashes (em / en dashes and stray hyphen connectors are stripped — these
    are the classic "AI wrote this" tells). Intra-word hyphens in proper names
    like "Scikit-Learn" are preserved so spelling stays correct.
  - Clean grammar, no awkward inserted fragments.
  - Hug the job description (weave in its overlapping skills/keywords).
  - Built on top of the resume (uses real experience highlights).

Deterministic and offline — same output in the app or a scheduled run.
"""

from __future__ import annotations
import re
from datetime import datetime
from typing import Dict, List

from scoring import parse_salary, resolve_profile_path  # noqa: F401  (re-export convenience)


# --------------------------------------------------------------------------- #
# Text hygiene
# --------------------------------------------------------------------------- #
def strip_dashes(text: str) -> str:
    """Remove em/en dashes and stray ' - ' connectors; keep word-internal hyphens."""
    text = text.replace("—", ", ").replace("–", ", ")  # em / en dash
    text = re.sub(r"\s+-\s+", ", ", text)                         # " - " connector
    text = re.sub(r",\s*,", ",", text)                           # collapse ", ,"
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([.,])", r"\1", text)                     # space before punctuation
    return text


def _join(items: List[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f", and {items[-1]}"


# --------------------------------------------------------------------------- #
# Skill matching
# --------------------------------------------------------------------------- #
def matched_skills(job: Dict, profile: Dict, limit: int = 8) -> List[str]:
    blob = f"{job.get('title','')} {job.get('description','')}".lower()
    seen, out = set(), []
    for sk in profile.get("skills", []):
        if re.search(r"(?<![A-Za-z])" + re.escape(sk.lower()) + r"(?![A-Za-z])", blob):
            if sk.lower() not in seen:
                seen.add(sk.lower())
                out.append(sk)
    return out[:limit]


# --------------------------------------------------------------------------- #
# Cover letter
# --------------------------------------------------------------------------- #
def cover_letter(job: Dict, profile: Dict) -> str:
    company = (job.get("company") or "your team").strip()
    title = (job.get("title") or "this role").strip()
    name = profile.get("name") or "[Your Name]"
    contact = profile.get("contact_line", "")
    headline = profile.get("headline", "").strip()

    skills = matched_skills(job, profile)
    focus = _join(skills[:3]) or "data analysis and turning data into decisions"
    strength = _join(skills[:5]) or "SQL, Python, and analytics"

    highlights = profile.get("experience_highlights", [])[:3]
    if highlights:
        bullets = "\n".join(f"  • {strip_dashes(h.rstrip('.'))}." for h in highlights)
        bullet_block = f"A few highlights I would bring to {company}:\n{bullets}\n\n"
    else:
        bullet_block = ""

    today = datetime.now().strftime("%B %d, %Y")

    body = (
        f"{today}\n\n"
        f"Dear {company} Hiring Team,\n\n"
        f"I am writing to apply for the {title} position at {company}. "
        f"{headline + ' ' if headline else ''}"
        f"Your description emphasizes {focus}, which is exactly where I have spent "
        f"my career, and I am confident I can contribute from day one.\n\n"
        f"{bullet_block}"
        f"My background maps closely to what you are looking for, particularly my "
        f"hands on experience with {strength}. I would welcome the opportunity to "
        f"discuss how I can help {company} turn data into faster, more confident "
        f"decisions.\n\n"
        f"Thank you for your time and consideration.\n\n"
        f"Sincerely,\n{name}"
    )
    if contact:
        body += f"\n{contact}"
    return strip_dashes(body).strip() + "\n"


def application_kit(job: Dict, profile: Dict) -> Dict:
    return {
        "title": job.get("title"),
        "company": job.get("company"),
        "apply_url": job.get("url"),
        "matched_skills": matched_skills(job, profile),
        "salary": parse_salary(job.get("comp_raw", "")),
        "cover_letter": cover_letter(job, profile),
    }


if __name__ == "__main__":
    import json, pathlib
    here = pathlib.Path(__file__).parent
    profile = json.loads(resolve_profile_path(here / "data").read_text())
    jobs = json.loads((here / "data" / "jobs.json").read_text())["jobs"]
    target = next((j for j in jobs if j.get("description")), jobs[0])
    print(cover_letter(target, profile))
