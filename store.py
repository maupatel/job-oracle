"""
JobOracle data layer (multi-user).

SQLite-backed storage for accounts, per-user profiles (parsed resume +
preferences), and per-user application trackers. Passwords are salted +
hashed with PBKDF2-HMAC-SHA256 (stdlib only — no external auth dependency).

NOTE ON HOSTING: on Streamlit Community Cloud the filesystem is ephemeral, so
this DB resets when the app restarts/sleeps. For durable multi-user data, point
JOBORACLE_DB at a persistent volume or swap the connection for a hosted Postgres
(Supabase/Neon free tier). The function signatures below are DB-agnostic enough
to make that swap contained.
"""

from __future__ import annotations
import hashlib
import json
import os
import pathlib
import sqlite3
import secrets as _secrets
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, List, Optional

DB_PATH = os.environ.get(
    "JOBORACLE_DB", str(pathlib.Path(__file__).parent / "data" / "joboracle.db")
)

_PBKDF2_ROUNDS = 200_000


@contextmanager
def _conn():
    pathlib.Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                email     TEXT UNIQUE NOT NULL,
                name      TEXT NOT NULL,
                pw_hash   TEXT NOT NULL,
                pw_salt   TEXT NOT NULL,
                created   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profiles (
                user_id      INTEGER PRIMARY KEY REFERENCES users(id),
                profile_json TEXT NOT NULL,
                updated      TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS applications (
                user_id  INTEGER NOT NULL REFERENCES users(id),
                job_id   TEXT NOT NULL,
                title    TEXT, company TEXT, location TEXT, url TEXT,
                score    INTEGER, status TEXT, notes TEXT, updated TEXT,
                PRIMARY KEY (user_id, job_id)
            );
            """
        )


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def _hash_pw(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ROUNDS
    ).hex()


def create_user(email: str, name: str, password: str) -> Dict:
    email = email.strip().lower()
    if not email or "@" not in email:
        raise ValueError("Please enter a valid email.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    salt = _secrets.token_hex(16)
    with _conn() as con:
        if con.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise ValueError("An account with that email already exists.")
        cur = con.execute(
            "INSERT INTO users (email, name, pw_hash, pw_salt, created) "
            "VALUES (?,?,?,?,?)",
            (email, name.strip() or email, _hash_pw(password, salt), salt,
             datetime.now().isoformat(timespec="seconds")),
        )
        return {"id": cur.lastrowid, "email": email, "name": name.strip() or email}


def verify_user(email: str, password: str) -> Optional[Dict]:
    email = email.strip().lower()
    with _conn() as con:
        row = con.execute(
            "SELECT id, email, name, pw_hash, pw_salt FROM users WHERE email=?",
            (email,),
        ).fetchone()
    if not row:
        return None
    if _secrets.compare_digest(_hash_pw(password, row["pw_salt"]), row["pw_hash"]):
        return {"id": row["id"], "email": row["email"], "name": row["name"]}
    return None


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
def save_profile(user_id: int, profile: Dict) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO profiles (user_id, profile_json, updated) VALUES (?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET profile_json=excluded.profile_json, "
            "updated=excluded.updated",
            (user_id, json.dumps(profile), datetime.now().isoformat(timespec="seconds")),
        )


def get_profile(user_id: int) -> Optional[Dict]:
    with _conn() as con:
        row = con.execute(
            "SELECT profile_json FROM profiles WHERE user_id=?", (user_id,)
        ).fetchone()
    return json.loads(row["profile_json"]) if row else None


# --------------------------------------------------------------------------- #
# Applications (tracker)
# --------------------------------------------------------------------------- #
def list_apps(user_id: int) -> Dict[str, Dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM applications WHERE user_id=?", (user_id,)
        ).fetchall()
    return {r["job_id"]: dict(r) for r in rows}


def upsert_app(user_id: int, job: Dict, status: str, notes: str = "") -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO applications "
            "(user_id, job_id, title, company, location, url, score, status, notes, updated) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(user_id, job_id) DO UPDATE SET "
            "status=excluded.status, notes=excluded.notes, score=excluded.score, "
            "updated=excluded.updated",
            (user_id, job["id"], job.get("title"), job.get("company"),
             job.get("location"), job.get("url"), job.get("score"),
             status, notes, datetime.now().strftime("%Y-%m-%d %H:%M")),
        )


def delete_app(user_id: int, job_id: str) -> None:
    with _conn() as con:
        con.execute(
            "DELETE FROM applications WHERE user_id=? AND job_id=?", (user_id, job_id)
        )


if __name__ == "__main__":
    init_db()
    print("DB initialized at", DB_PATH)
