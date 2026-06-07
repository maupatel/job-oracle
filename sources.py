"""
Multi-source job aggregation.

Pulls live listings from JSearch (RapidAPI — aggregates LinkedIn, Indeed,
Glassdoor, ZipRecruiter) and Adzuna, normalizes them into one record schema,
merges and dedupes. If no API keys are configured it transparently falls back
to the bundled snapshot in data/jobs.json so the app still works.

Keys are read from Streamlit secrets first, then environment variables:
    RAPIDAPI_KEY            (JSearch)
    ADZUNA_APP_ID, ADZUNA_APP_KEY

Record schema (matches scoring.py):
    id, title, company, location, job_type, posted, comp_raw, url, source, description
"""

from __future__ import annotations
import json
import os
import pathlib
from typing import Dict, List, Optional

import requests

HERE = pathlib.Path(__file__).parent
SNAPSHOT = HERE / "data" / "jobs.json"
TIMEOUT = 20


def _secret(key: str) -> Optional[str]:
    try:
        import streamlit as st
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key)


def keys_present() -> Dict[str, bool]:
    return {
        "jsearch": bool(_secret("RAPIDAPI_KEY")),
        "adzuna": bool(_secret("ADZUNA_APP_ID") and _secret("ADZUNA_APP_KEY")),
    }


# --------------------------------------------------------------------------- #
# JSearch (RapidAPI)
# --------------------------------------------------------------------------- #
def fetch_jsearch(query: str, location: str = "remote", pages: int = 1) -> List[Dict]:
    key = _secret("RAPIDAPI_KEY")
    if not key:
        return []
    try:
        r = requests.get(
            "https://jsearch.p.rapidapi.com/search",
            headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"},
            params={"query": f"{query} in {location}", "num_pages": str(pages)},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        out = []
        for j in r.json().get("data", []):
            comp = ""
            if j.get("job_min_salary") and j.get("job_max_salary"):
                period = (j.get("job_salary_period") or "year").lower()
                unit = "an hour" if period == "hour" else "a year"
                comp = f"${j['job_min_salary']:,.0f} - ${j['job_max_salary']:,.0f} {unit}"
            city = j.get("job_city") or ""
            state = j.get("job_state") or ""
            loc = j.get("job_is_remote") and "Remote" or ", ".join(p for p in (city, state) if p)
            out.append({
                "id": j.get("job_id") or f"js_{abs(hash(j.get('job_apply_link','')))}",
                "title": j.get("job_title", ""),
                "company": j.get("employer_name", ""),
                "location": loc or "—",
                "job_type": (j.get("job_employment_type") or "").lower().replace("_", ""),
                "posted": (j.get("job_posted_at_datetime_utc") or "")[:10],
                "comp_raw": comp or "N/A",
                "url": j.get("job_apply_link", ""),
                "source": f"JSearch/{j.get('job_publisher','')}",
                "description": (j.get("job_description") or "")[:2500],
            })
        return out
    except Exception as e:
        print("JSearch error:", e)
        return []


# --------------------------------------------------------------------------- #
# Adzuna
# --------------------------------------------------------------------------- #
def fetch_adzuna(query: str, location: str = "", country: str = "us",
                 results: int = 25) -> List[Dict]:
    app_id, app_key = _secret("ADZUNA_APP_ID"), _secret("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return []
    try:
        params = {
            "app_id": app_id, "app_key": app_key,
            "what": query, "results_per_page": results,
            "content-type": "application/json",
        }
        if location and location.lower() != "remote":
            params["where"] = location
        r = requests.get(
            f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
            params=params, timeout=TIMEOUT,
        )
        r.raise_for_status()
        out = []
        for j in r.json().get("results", []):
            lo, hi = j.get("salary_min"), j.get("salary_max")
            comp = f"${lo:,.0f} - ${hi:,.0f} a year" if lo and hi else "N/A"
            out.append({
                "id": str(j.get("id") or f"az_{abs(hash(j.get('redirect_url','')))}"),
                "title": j.get("title", ""),
                "company": (j.get("company") or {}).get("display_name", ""),
                "location": (j.get("location") or {}).get("display_name", "—"),
                "job_type": (j.get("contract_time") or "").replace("_time", "").replace("full", "fulltime").replace("part", "parttime"),
                "posted": (j.get("created") or "")[:10],
                "comp_raw": comp,
                "url": j.get("redirect_url", ""),
                "source": "Adzuna",
                "description": (j.get("description") or "")[:2500],
            })
        return out
    except Exception as e:
        print("Adzuna error:", e)
        return []


# --------------------------------------------------------------------------- #
# Merge + snapshot fallback
# --------------------------------------------------------------------------- #
def _dedupe(jobs: List[Dict]) -> List[Dict]:
    seen, out = set(), []
    for j in jobs:
        key = (j.get("title", "").lower().strip(), j.get("company", "").lower().strip())
        if key in seen or not j.get("title"):
            continue
        seen.add(key)
        out.append(j)
    return out


def load_snapshot() -> List[Dict]:
    if SNAPSHOT.exists():
        data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        jobs = data.get("jobs", [])
        for j in jobs:
            j.setdefault("source", data.get("source", "Snapshot"))
        return jobs
    return []


def fetch_all(titles: List[str], location: str = "remote") -> Dict:
    """Aggregate across all configured sources for each target title."""
    present = keys_present()
    collected: List[Dict] = []
    if present["jsearch"] or present["adzuna"]:
        for t in titles[:4]:
            collected += fetch_jsearch(t, location)
            collected += fetch_adzuna(t, location)
        jobs = _dedupe(collected)
        if jobs:
            srcs = sorted({j["source"].split("/")[0] for j in jobs})
            return {"jobs": jobs, "live": True, "sources": srcs}
    # fallback
    return {"jobs": load_snapshot(), "live": False, "sources": ["Snapshot (Indeed)"]}


if __name__ == "__main__":
    print("Keys present:", keys_present())
    res = fetch_all(["Senior Data Analyst", "Data Engineer"])
    print(f"live={res['live']} sources={res['sources']} jobs={len(res['jobs'])}")
