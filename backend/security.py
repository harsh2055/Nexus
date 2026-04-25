import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from .settings import SESSION_DAYS


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256$120000${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt, digest = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(rounds)).hex()
        return hmac.compare_digest(candidate, digest)
    except ValueError:
        return False


def public_user(row: sqlite3.Row | dict) -> dict:
    return {"id": row["id"], "name": row["name"], "email": row["email"]}


def seed_default_user(db: sqlite3.Connection) -> None:
    exists = db.execute("SELECT 1 FROM users WHERE email = ?", ("alex@nexus.io",)).fetchone()
    if exists:
        return
    db.execute(
        "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
        ("u1", "Alex Johnson", "alex@nexus.io", hash_password("admin123"), iso_now()),
    )
    db.execute("INSERT OR IGNORE INTO counters VALUES (?, ?)", ("u", 100))


def create_session(db: sqlite3.Connection, user_id: str) -> tuple[str, datetime, str]:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires = now_utc() + timedelta(days=SESSION_DAYS)
    db.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
        (token, user_id, csrf_token, expires.isoformat(), iso_now()),
    )
    return token, expires, csrf_token

