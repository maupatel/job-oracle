"""
Resume upload + parsing.

Accepts a PDF, DOCX, or TXT upload, extracts the raw text, and builds a profile
dict compatible with scoring.py / apply_assist.py (skills, title_keywords,
seniority_keywords, headline, experience highlights, raw resume_text).

PDF parsing uses pypdf; DOCX uses python-docx. Both are pure-Python and run on
Streamlit Cloud.
"""

from __future__ import annotations
import io
import json
import pathlib
import re
from typing import Dict, List

HERE = pathlib.Path(__file__).parent

# Skill vocabulary we try to detect in resume text. Extend freely.
SKILL_VOCAB = [
    "AWS", "S3", "Lambda", "Azure", "GCP", "BigQuery", "Data Mining", "A/B Testing",
    "Python", "Pandas", "NumPy", "Scikit-Learn", "PyTorch", "TensorFlow", "Keras",
    "OpenAI API", "SAS", "Power BI", "Looker", "Tableau", "QlikView", "Data Warehousing",
    "Time-Series Forecasting", "Hive", "NoSQL", "MongoDB", "Alteryx", "Machine Learning",
    "Deep Learning", "NLP", "Process Automation", "Java", "Scala", "C++", "SQL",
    "Snowflake", "Redshift", "PostgreSQL", "MySQL", "Oracle", "Databricks", "Spark",
    "PySpark", "Kafka", "Airflow", "dbt", "ETL", "ELT", "Predictive Modeling",
    "Clustering", "K-Means", "Excel", "Power Query", "VBA", "Fraud Detection",
    "Statistical Analysis", "LLM", "R", "Hadoop", "BI", "Analytics", "Git", "Docker",
    "Kubernetes", "REST API", "Data Modeling", "Data Visualization",
]

TITLE_KEYWORDS = [
    "data analyst", "data engineer", "business analyst", "bi analyst",
    "business intelligence", "analytics engineer", "analytics", "data scientist",
    "insights", "machine learning engineer",
]

SENIORITY_KEYWORDS = ["senior", "sr.", "sr ", "lead", "principal", "staff", "head of"]

COMMON_TITLES = [
    "Senior Data Analyst", "Data Analyst", "Data Engineer", "Senior Data Engineer",
    "Business Analyst", "BI Analyst", "Analytics Engineer", "Data Scientist",
    "Machine Learning Engineer",
]


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _extract_docx(data: bytes) -> str:
    import docx
    d = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in d.paragraphs)


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return _extract_pdf(data)
    if name.endswith(".docx"):
        return _extract_docx(data)
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="ignore")
    raise ValueError("Unsupported file type. Upload a PDF, DOCX, or TXT resume.")


def detect_skills(text: str) -> List[str]:
    low = text.lower()
    hits = []
    for sk in SKILL_VOCAB:
        if re.search(r"(?<![A-Za-z])" + re.escape(sk.lower()) + r"(?![A-Za-z])", low):
            hits.append(sk)
    return hits


def guess_titles(text: str) -> List[str]:
    low = text.lower()
    found = [t for t in COMMON_TITLES if t.lower() in low]
    return found[:4] or ["Data Analyst", "Business Analyst"]


def _first_highlights(text: str, n: int = 3) -> List[str]:
    """Pull a few resume bullet-like lines as experience highlights."""
    lines = [re.sub(r"^[\s•\-\*•]+", "", ln).strip() for ln in text.splitlines()]
    cand = [
        ln for ln in lines
        if 40 <= len(ln) <= 240 and any(c.isalpha() for c in ln)
        and not ln.lower().startswith(("email", "phone", "linkedin", "http"))
    ]
    return cand[:n]


def build_profile(name: str, filename: str, data: bytes,
                  min_salary: int = 0, prefers_remote: bool = True) -> Dict:
    text = extract_text(filename, data).strip()
    skills = detect_skills(text)
    titles = guess_titles(text)
    highlights = _first_highlights(text)
    headline = highlights[0] if highlights else (
        f"{titles[0]} with experience across {', '.join(skills[:4]) or 'data and analytics'}."
    )
    return {
        "name": name.strip() or "Candidate",
        "current_role": titles[0] if titles else "Data Professional",
        "target_titles": titles,
        "min_salary": int(min_salary or 0),
        "prefers_remote": bool(prefers_remote),
        "preferred_job_types": ["fulltime"],
        "skills": skills or ["SQL", "Python", "Analytics"],
        "headline": headline,
        "experience_highlights": highlights,
        "contact_line": "",
        "resume_text": text[:12000],
        "title_keywords": TITLE_KEYWORDS,
        "seniority_keywords": SENIORITY_KEYWORDS,
    }


if __name__ == "__main__":
    # quick check against the bundled example resume text, if present
    print("Skill vocab size:", len(SKILL_VOCAB))
