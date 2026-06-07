"""
JobOracle — multi-user job-search web app.

Run:  streamlit run app.py

Flow:
    1. Login / sign up (accounts stored in SQLite via store.py)
    2. First-time onboarding: enter your name + upload your resume (PDF/DOCX/TXT)
    3. Main app:
         🔎 Matches      — live jobs (JSearch + Adzuna, or snapshot) scored vs your resume
         ✍️ Apply-assist — dash-free tailored cover letter, download as PDF or Word
         📋 Tracker      — your personal application board

Job data: sources.fetch_all() aggregates JSearch (LinkedIn/Indeed/Glassdoor/
ZipRecruiter) + Adzuna when API keys are set in Streamlit secrets; otherwise it
falls back to the bundled snapshot so the app always works.
"""

import streamlit as st

import store
from scoring import score_all
from sources import fetch_all, keys_present
from resume_parse import build_profile
from apply_assist import application_kit
from export import to_pdf, to_docx

STATUSES = ["Saved", "Applied", "Interviewing", "Offer", "Rejected"]
STATUS_ICON = {"Saved": "🔖", "Applied": "📨", "Interviewing": "🗣️",
               "Offer": "🎉", "Rejected": "❌"}

st.set_page_config(page_title="JobOracle", page_icon="🧭", layout="wide")
store.init_db()


# --------------------------------------------------------------------------- #
# Cached job fetch (keyed on titles + manual refresh token)
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=1800, show_spinner="Fetching jobs…")
def fetch_jobs_cached(titles_tuple, location, refresh_token):
    return fetch_all(list(titles_tuple), location)


# --------------------------------------------------------------------------- #
# 1. AUTH
# --------------------------------------------------------------------------- #
def render_auth():
    st.title("🧭 JobOracle")
    st.caption("Aggregate jobs, score them against your resume, and draft tailored "
               "cover letters — in one place.")
    login_tab, signup_tab = st.tabs(["Log in", "Sign up"])

    with login_tab:
        with st.form("login"):
            email = st.text_input("Email")
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Log in", use_container_width=True):
                user = store.verify_user(email, pw)
                if user:
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("Incorrect email or password.")

    with signup_tab:
        with st.form("signup"):
            name = st.text_input("Your name")
            email = st.text_input("Email", key="su_email")
            pw = st.text_input("Password (6+ characters)", type="password", key="su_pw")
            if st.form_submit_button("Create account", use_container_width=True):
                try:
                    user = store.create_user(email, name, pw)
                    st.session_state.user = user
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


# --------------------------------------------------------------------------- #
# 2. ONBOARDING
# --------------------------------------------------------------------------- #
def render_onboarding(user):
    st.title("👋 Welcome to JobOracle")
    st.write(f"Hi **{user['name']}** — let's set up your profile so we can score "
             "jobs against your real background.")
    with st.form("onboard"):
        name = st.text_input("Name shown on your cover letters", value=user["name"])
        contact = st.text_input("Contact line for cover letters (email / phone)",
                                 value=user["email"])
        up = st.file_uploader("Upload your resume (PDF, DOCX, or TXT)",
                              type=["pdf", "docx", "txt"])
        col1, col2 = st.columns(2)
        min_salary = col1.number_input("Minimum salary ($/yr)", 0, 1_000_000, 120000, 5000)
        remote = col2.checkbox("Prefer remote", value=True)
        submitted = st.form_submit_button("Build my profile", use_container_width=True)

    if submitted:
        if not up:
            st.error("Please upload a resume file to continue.")
            return
        try:
            profile = build_profile(name, up.name, up.getvalue(),
                                    min_salary=min_salary, prefers_remote=remote)
            profile["contact_line"] = contact
            store.save_profile(user["id"], profile)
            st.success("Profile built! Loading your matches…")
            st.rerun()
        except Exception as e:
            st.error(f"Could not read that resume: {e}")


# --------------------------------------------------------------------------- #
# 3. MAIN APP
# --------------------------------------------------------------------------- #
def render_sidebar(user, profile):
    with st.sidebar:
        st.markdown(f"**{user['name']}**  \n{user['email']}")
        if st.button("Log out", use_container_width=True):
            del st.session_state.user
            st.rerun()
        st.divider()

        present = keys_present()
        live = present["jsearch"] or present["adzuna"]
        st.caption("**Data sources**")
        st.write("🟢 JSearch" if present["jsearch"] else "⚪ JSearch (no key)")
        st.write("🟢 Adzuna" if present["adzuna"] else "⚪ Adzuna (no key)")
        if not live:
            st.caption("Add RAPIDAPI_KEY / ADZUNA_APP_ID+KEY in secrets for live "
                       "LinkedIn+Indeed+Glassdoor results. Showing snapshot for now.")
        if st.button("🔄 Refresh jobs", use_container_width=True):
            st.session_state.refresh = st.session_state.get("refresh", 0) + 1
            st.rerun()

        st.divider()
        with st.expander("⚙️ Update resume / preferences"):
            st.caption("Re-upload to rebuild your profile.")
            up = st.file_uploader("New resume", type=["pdf", "docx", "txt"], key="reup")
            ms = st.number_input("Minimum salary ($/yr)", 0, 1_000_000,
                                 int(profile.get("min_salary", 120000)), 5000, key="rems")
            if st.button("Save changes"):
                try:
                    if up:
                        new = build_profile(profile.get("name", user["name"]),
                                            up.name, up.getvalue(), min_salary=ms,
                                            prefers_remote=profile.get("prefers_remote", True))
                        new["contact_line"] = profile.get("contact_line", user["email"])
                        store.save_profile(user["id"], new)
                    else:
                        profile["min_salary"] = int(ms)
                        store.save_profile(user["id"], profile)
                    st.success("Saved.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))


def render_matches(user, scored, profile, apps):
    with st.sidebar:
        st.divider()
        st.caption("**Filters**")
        min_score = st.slider("Minimum fit score", 0, 100, 55, 5)
        remote_only = st.checkbox("Remote only")
        hide_low_pay = st.checkbox("Hide pay below my floor", value=True)
        query = st.text_input("Keyword in title/company").strip().lower()

    def keep(j):
        if j["score"] < min_score:
            return False
        if remote_only and "remote" not in (j["location"] + j["title"]).lower():
            return False
        if hide_low_pay and j["salary"]["known"] and \
                j["salary"]["mid"] < profile.get("min_salary", 0):
            return False
        if query and query not in (j["title"] + j["company"]).lower():
            return False
        return True

    shown = [j for j in scored if keep(j)]
    st.subheader(f"{len(shown)} matches")
    for j in shown:
        sal = j["salary"]
        sal_txt = f"${sal['min']/1000:.0f}k–${sal['max']/1000:.0f}k" if sal["known"] else "salary n/a"
        tracked = apps.get(j["id"])
        badge = f" · {STATUS_ICON.get(tracked['status'],'')} {tracked['status']}" if tracked else ""
        src = j.get("source", "")
        with st.expander(f"**{j['score']}**  ·  {j['title']} — {j['company']}  ·  "
                         f"{j['location']}  ·  {sal_txt}{badge}"):
            c = j["components"]
            st.caption(f"source: {src} · title {c['title']}/40 · pay {c['pay']}/30 · "
                       f"type {c['type']}/15 · skills {c['skills']}/15")
            for r in j["reasons"]:
                st.write("• " + r)
            if j.get("url"):
                st.markdown(f"[🔗 Open / apply]({j['url']})")
            cols = st.columns([2, 1])
            choice = cols[0].selectbox("Track as", ["—"] + STATUSES,
                                       index=(["—"] + STATUSES).index(tracked["status"])
                                       if tracked else 0, key=f"sel_{j['id']}")
            if cols[1].button("Save", key=f"sv_{j['id']}"):
                if choice == "—":
                    store.delete_app(user["id"], j["id"])
                else:
                    store.upsert_app(user["id"], j, choice)
                st.rerun()


def render_apply(user, scored, profile):
    st.subheader("Tailored cover letter")
    st.caption("Drafted from your resume highlights + the skills that overlap this "
               "job. No dashes, clean grammar. Edit it, then download as PDF or Word.")
    if not scored:
        st.info("No jobs to choose from.")
        return
    labels = {f"[{j['score']}] {j['title']} — {j['company']}": j for j in scored}
    pick = st.selectbox("Pick a job", list(labels.keys()))
    job = labels[pick]
    kit = application_kit(job, profile)

    st.markdown(f"**Matched skills:** {', '.join(kit['matched_skills']) or '—'}")
    if kit["apply_url"]:
        st.markdown(f"[🔗 Open / apply]({kit['apply_url']})")

    letter = st.text_area("Cover letter (editable)", value=kit["cover_letter"], height=440)
    base = f"cover_{job['company'].replace(' ', '_')}"
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇️ PDF", to_pdf(letter, base), file_name=f"{base}.pdf",
                       mime="application/pdf", use_container_width=True)
    c2.download_button("⬇️ Word", to_docx(letter, base), file_name=f"{base}.docx",
                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                       use_container_width=True)
    if c3.button("Track as Applied", use_container_width=True):
        store.upsert_app(user["id"], job, "Applied")
        st.success(f"Tracked {job['company']} as Applied.")


def render_tracker(user):
    apps = store.list_apps(user["id"])
    if not apps:
        st.info("No tracked applications yet. Add some from the Matches tab.")
        return
    cols = st.columns(len(STATUSES))
    for col, status in zip(cols, STATUSES):
        with col:
            items = [a for a in apps.values() if a["status"] == status]
            st.markdown(f"### {STATUS_ICON[status]} {status} ({len(items)})")
            for a in sorted(items, key=lambda x: x.get("score") or 0, reverse=True):
                with st.container(border=True):
                    st.markdown(f"**{a['title']}**")
                    st.caption(f"{a['company']} · {a['location']} · fit {a['score']}")
                    if a.get("url"):
                        st.markdown(f"[apply]({a['url']})")
                    new = st.selectbox("status", STATUSES, index=STATUSES.index(status),
                                       key=f"trk_{a['job_id']}", label_visibility="collapsed")
                    note = st.text_input("note", value=a.get("notes") or "",
                                         key=f"nt_{a['job_id']}",
                                         label_visibility="collapsed", placeholder="notes…")
                    b1, b2 = st.columns(2)
                    if b1.button("Update", key=f"up_{a['job_id']}"):
                        store.upsert_app(user["id"], {"id": a["job_id"], "title": a["title"],
                                         "company": a["company"], "location": a["location"],
                                         "url": a["url"], "score": a["score"]}, new, note)
                        st.rerun()
                    if b2.button("Remove", key=f"rm_{a['job_id']}"):
                        store.delete_app(user["id"], a["job_id"])
                        st.rerun()


def render_main(user, profile):
    render_sidebar(user, profile)
    titles = tuple(profile.get("target_titles") or ["Data Analyst"])
    location = "remote" if profile.get("prefers_remote", True) else ""
    res = fetch_jobs_cached(titles, location, st.session_state.get("refresh", 0))
    scored = score_all(res["jobs"], profile)
    apps = store.list_apps(user["id"])

    st.title("🧭 JobOracle")
    live_txt = "live: " + ", ".join(res["sources"]) if res["live"] else f"snapshot ({res['sources'][0]})"
    st.caption(f"{len(scored)} jobs · {live_txt} · floor ${profile.get('min_salary',0)/1000:.0f}k "
               f"· targets: {', '.join(titles)}")

    t1, t2, t3 = st.tabs(["🔎 Matches", "✍️ Apply-assist", f"📋 Tracker ({len(apps)})"])
    with t1:
        render_matches(user, scored, profile, apps)
    with t2:
        render_apply(user, scored, profile)
    with t3:
        render_tracker(user)


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
if "user" not in st.session_state:
    render_auth()
else:
    user = st.session_state.user
    profile = store.get_profile(user["id"])
    if not profile:
        render_onboarding(user)
    else:
        render_main(user, profile)
