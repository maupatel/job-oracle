"""
JobOracle — local job-search command center.

Run:  streamlit run app.py

Data flow:
    data/jobs.json     <- refreshed by the agent / daily scheduled task (live Indeed)
    data/profile.json  <- your resume + preferences
    data/applications.json <- your tracker board (written by this app)

This app does NOT call the internet itself — it visualizes + scores whatever is
in jobs.json and manages your application pipeline. Re-pulling live jobs is the
job of the data engine (me, or the Stage-3 scheduled task).
"""

import json
import pathlib
from datetime import datetime

import streamlit as st

from scoring import score_all, resolve_profile_path
from apply_assist import application_kit

HERE = pathlib.Path(__file__).parent
DATA = HERE / "data"
JOBS_FILE = DATA / "jobs.json"
PROFILE_FILE = resolve_profile_path(DATA)
APPS_FILE = DATA / "applications.json"

STATUSES = ["Saved", "Applied", "Interviewing", "Offer", "Rejected"]
STATUS_COLOR = {
    "Saved": "🔖", "Applied": "📨", "Interviewing": "🗣️",
    "Offer": "🎉", "Rejected": "❌",
}

st.set_page_config(page_title="JobOracle", page_icon="🧭", layout="wide")


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def load_apps():
    return load_json(APPS_FILE, {})


def save_apps(apps):
    APPS_FILE.write_text(json.dumps(apps, indent=2), encoding="utf-8")


def set_status(job, status):
    apps = load_apps()
    if status is None:
        apps.pop(job["id"], None)
    else:
        existing = apps.get(job["id"], {})
        apps[job["id"]] = {
            "id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "url": job["url"],
            "score": job["score"],
            "status": status,
            "notes": existing.get("notes", ""),
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    save_apps(apps)


# --------------------------------------------------------------------------- #
# Load + score
# --------------------------------------------------------------------------- #
profile = load_json(PROFILE_FILE, {})
raw = load_json(JOBS_FILE, {"jobs": [], "fetched_at": "—"})
scored = score_all(raw.get("jobs", []), profile)
apps = load_apps()

st.title("🧭 JobOracle")
st.caption(
    f"{len(scored)} live jobs · source: {raw.get('source','?')} · "
    f"pulled {raw.get('fetched_at','—')} · floor ${profile.get('min_salary',0)/1000:.0f}k"
)

tab_match, tab_apply, tab_track = st.tabs(
    ["🔎 Matches", "✍️ Apply-assist", f"📋 Tracker ({len(apps)})"]
)

# --------------------------------------------------------------------------- #
# MATCHES
# --------------------------------------------------------------------------- #
with tab_match:
    with st.sidebar:
        st.header("Filters")
        min_score = st.slider("Minimum fit score", 0, 100, 60, 5)
        remote_only = st.checkbox("Remote only", value=False)
        hide_below_floor = st.checkbox(
            "Hide pay below my floor", value=True,
            help="Drops jobs whose midpoint salary is under your minimum. "
                 "Jobs with no listed salary are kept.",
        )
        ft_only = st.checkbox("Full-time only", value=False)
        query = st.text_input("Keyword in title/company").strip().lower()
        st.divider()
        st.caption("Edit data/profile.json to change target titles, skills, "
                   "or salary floor, then refresh.")

    def keep(j):
        if j["score"] < min_score:
            return False
        if remote_only and "remote" not in (j["location"] + j["title"]).lower():
            return False
        if ft_only and (j.get("job_type") or "") != "fulltime":
            return False
        if hide_below_floor:
            sal = j["salary"]
            if sal["known"] and sal["mid"] < profile.get("min_salary", 0):
                return False
        if query and query not in (j["title"] + j["company"]).lower():
            return False
        return True

    shown = [j for j in scored if keep(j)]
    st.subheader(f"{len(shown)} matches")

    for j in shown:
        sal = j["salary"]
        sal_txt = (
            f"${sal['min']/1000:.0f}k–${sal['max']/1000:.0f}k"
            if sal["known"] else "salary n/a"
        )
        tracked = apps.get(j["id"])
        badge = f" · {STATUS_COLOR.get(tracked['status'],'')} {tracked['status']}" if tracked else ""
        header = f"**{j['score']}**  ·  {j['title']} — {j['company']}  ·  {j['location']}  ·  {sal_txt}{badge}"
        with st.expander(header, expanded=False):
            c1, c2 = st.columns([3, 1])
            with c1:
                comp = j["components"]
                st.caption(
                    f"title {comp['title']}/40 · pay {comp['pay']}/30 · "
                    f"type {comp['type']}/15 · skills {comp['skills']}/15"
                )
                for r in j["reasons"]:
                    st.write("• " + r)
                st.markdown(f"[🔗 Open / apply on Indeed]({j['url']})")
            with c2:
                cur = tracked["status"] if tracked else "—"
                choice = st.selectbox(
                    "Track as", ["—"] + STATUSES,
                    index=(["—"] + STATUSES).index(cur) if cur in STATUSES else 0,
                    key=f"sel_{j['id']}",
                )
                if st.button("Save", key=f"btn_{j['id']}"):
                    set_status(j, None if choice == "—" else choice)
                    st.rerun()

# --------------------------------------------------------------------------- #
# APPLY-ASSIST
# --------------------------------------------------------------------------- #
with tab_apply:
    st.subheader("Generate a tailored cover letter")
    st.caption(
        "Drafts a letter from your resume highlights + the skills that overlap this "
        "job's description. Review and edit, download, then open the apply link and "
        "submit yourself."
    )
    if not scored:
        st.info("No jobs loaded.")
    else:
        labels = {
            f"[{j['score']}] {j['title']} — {j['company']}": j for j in scored
        }
        pick = st.selectbox("Pick a job", list(labels.keys()))
        job = labels[pick]
        kit = application_kit(job, profile)

        sk = ", ".join(kit["matched_skills"]) or "—"
        st.markdown(f"**Matched skills:** {sk}")
        st.markdown(f"[🔗 Open / apply on Indeed]({kit['apply_url']})")

        letter = st.text_area(
            "Cover letter (editable)", value=kit["cover_letter"], height=420
        )
        fname = f"cover_{job['company'].replace(' ', '_')}.txt"
        st.download_button("⬇️ Download letter", letter, file_name=fname)
        if st.button("Track this as Applied"):
            set_status(job, "Applied")
            st.success(f"Added {job['company']} to tracker as Applied.")

# --------------------------------------------------------------------------- #
# TRACKER
# --------------------------------------------------------------------------- #
with tab_track:
    apps = load_apps()
    if not apps:
        st.info("No tracked applications yet. Add some from the Matches tab.")
    else:
        cols = st.columns(len(STATUSES))
        for col, status in zip(cols, STATUSES):
            with col:
                items = [a for a in apps.values() if a["status"] == status]
                st.markdown(f"### {STATUS_COLOR[status]} {status} ({len(items)})")
                for a in sorted(items, key=lambda x: x["score"], reverse=True):
                    with st.container(border=True):
                        st.markdown(f"**{a['title']}**")
                        st.caption(f"{a['company']} · {a['location']} · fit {a['score']}")
                        st.markdown(f"[apply]({a['url']})")
                        new = st.selectbox(
                            "status", STATUSES, index=STATUSES.index(status),
                            key=f"trk_{a['id']}", label_visibility="collapsed",
                        )
                        note = st.text_input(
                            "note", value=a.get("notes", ""),
                            key=f"note_{a['id']}", label_visibility="collapsed",
                            placeholder="notes…",
                        )
                        cc1, cc2 = st.columns(2)
                        if cc1.button("Update", key=f"upd_{a['id']}"):
                            apps[a["id"]]["status"] = new
                            apps[a["id"]]["notes"] = note
                            apps[a["id"]]["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                            save_apps(apps)
                            st.rerun()
                        if cc2.button("Remove", key=f"del_{a['id']}"):
                            apps.pop(a["id"], None)
                            save_apps(apps)
                            st.rerun()
