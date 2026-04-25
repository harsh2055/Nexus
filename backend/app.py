from __future__ import annotations

import json
import hmac
import re
import sqlite3
import time
from datetime import date, datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .settings import DB_PATH, INDEX_PATH, STATIC_ROOT
from .seeds import TEAM, PROJECTS, PROJECT_MEMBERS, TASKS
from .security import create_session, hash_password, iso_now, public_user, seed_default_user, verify_password

RATE_LIMITS: dict[tuple[str, str], list[float]] = {}
MAX_BODY_BYTES = 64 * 1024
AUTH_WINDOW_SECONDS = 60
AUTH_MAX_ATTEMPTS = 8


def hmac_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db() -> None:
    with connect() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
              token TEXT PRIMARY KEY,
              user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              csrf_token TEXT,
              expires_at TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS team (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              role TEXT NOT NULL,
              email TEXT DEFAULT '',
              color TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              desc TEXT DEFAULT '',
              color TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              created TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_members (
              project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
              member_id TEXT NOT NULL REFERENCES team(id) ON DELETE CASCADE,
              PRIMARY KEY (project_id, member_id)
            );

            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
              title TEXT NOT NULL,
              desc TEXT DEFAULT '',
              status TEXT NOT NULL DEFAULT 'todo',
              priority TEXT NOT NULL DEFAULT 'medium',
              assignee_id TEXT REFERENCES team(id) ON DELETE SET NULL,
              due TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_tags (
              task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
              tag TEXT NOT NULL,
              PRIMARY KEY (task_id, tag)
            );

            CREATE TABLE IF NOT EXISTS comments (
              id TEXT PRIMARY KEY,
              task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
              member_id TEXT REFERENCES team(id) ON DELETE SET NULL,
              text TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS notifications (
              id TEXT PRIMARY KEY,
              text TEXT NOT NULL,
              color TEXT NOT NULL,
              is_read INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS counters (
              name TEXT PRIMARY KEY,
              value INTEGER NOT NULL
            );
            """
        )
        ensure_schema(db)
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso_now(),))
        seed_default_user(db)
        existing = db.execute("SELECT COUNT(*) AS count FROM projects").fetchone()["count"]
        if existing:
            return
        db.executemany("INSERT INTO team VALUES (?, ?, ?, ?, ?)", TEAM)
        db.executemany("INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)", PROJECTS)
        for project_id, member_ids in PROJECT_MEMBERS.items():
            db.executemany("INSERT INTO project_members VALUES (?, ?)", [(project_id, member_id) for member_id in member_ids])
        for task_id, project_id, title, desc, status, priority, assignee, due, tags in TASKS:
            db.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, project_id, title, desc, status, priority, assignee, due),
            )
            db.executemany("INSERT INTO task_tags VALUES (?, ?)", [(task_id, tag) for tag in tags])
        now = datetime.utcnow()
        db.execute(
            "INSERT INTO comments VALUES (?, ?, ?, ?, ?)",
            ("c1", "k1", "t1", "This gives the product a much calmer rhythm.", (now - timedelta(hours=2)).isoformat()),
        )
        db.execute(
            "INSERT INTO comments VALUES (?, ?, ?, ?, ?)",
            ("c2", "k7", "t5", "Add expired-token handling before review.", (now - timedelta(minutes=30)).isoformat()),
        )
        notifications = [
            ("n1", "Sarah Chen moved Build component library to review", "#38BDF8", 0, (now - timedelta(minutes=12)).isoformat()),
            ("n2", "Marcus Rivera completed Design new color system", "#34D399", 0, (now - timedelta(hours=1)).isoformat()),
            ("n3", "Jordan Kim commented on Implement authentication flow", "#C084FC", 1, (now - timedelta(hours=5)).isoformat()),
        ]
        db.executemany("INSERT INTO notifications VALUES (?, ?, ?, ?, ?)", notifications)
        db.executemany(
            "INSERT INTO counters VALUES (?, ?)",
            [("p", 100), ("t", 100), ("k", 100), ("c", 100), ("n", 100), ("u", 100)],
        )


def ensure_schema(db: sqlite3.Connection) -> None:
    session_cols = [row["name"] for row in db.execute("PRAGMA table_info(sessions)")]
    if "csrf_token" not in session_cols:
        db.execute("ALTER TABLE sessions ADD COLUMN csrf_token TEXT")
        db.execute("UPDATE sessions SET csrf_token = token WHERE csrf_token IS NULL")
    db.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
        CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due);
        CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at);
        """
    )


def next_id(db: sqlite3.Connection, prefix: str) -> str:
    row = db.execute("SELECT value FROM counters WHERE name = ?", (prefix,)).fetchone()
    value = row["value"] if row else 1
    db.execute(
        "INSERT INTO counters(name, value) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value",
        (prefix, value + 1),
    )
    return f"{prefix}{value}"


def rows(sql: str, params: tuple = ()) -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute(sql, params)]


def add_notification(db: sqlite3.Connection, text: str, color: str = "#E8A030") -> None:
    db.execute(
        "INSERT INTO notifications VALUES (?, ?, ?, ?, ?)",
        (next_id(db, "n"), text, color, 0, datetime.utcnow().isoformat()),
    )


def project_payload(db: sqlite3.Connection, project_id: str | None = None) -> list[dict] | dict | None:
    params: tuple = ()
    where = ""
    if project_id:
        where = "WHERE p.id = ?"
        params = (project_id,)
    projects = [dict(row) for row in db.execute(f"SELECT p.* FROM projects p {where} ORDER BY created DESC", params)]
    for project in projects:
        project["members"] = [
            row["member_id"]
            for row in db.execute("SELECT member_id FROM project_members WHERE project_id = ?", (project["id"],))
        ]
    if project_id:
        return projects[0] if projects else None
    return projects


def task_payload(db: sqlite3.Connection, task_id: str | None = None, query: dict | None = None) -> list[dict] | dict | None:
    sql = """
      SELECT t.*, p.name AS project_name, p.color AS project_color, tm.name AS assignee_name, tm.color AS assignee_color
      FROM tasks t
      JOIN projects p ON p.id = t.project_id
      LEFT JOIN team tm ON tm.id = t.assignee_id
    """
    clauses: list[str] = []
    params: list[str] = []
    if task_id:
        clauses.append("t.id = ?")
        params.append(task_id)
    if query:
        if query.get("project"):
            clauses.append("t.project_id = ?")
            params.append(query["project"][0])
        if query.get("status"):
            clauses.append("t.status = ?")
            params.append(query["status"][0])
        if query.get("priority"):
            clauses.append("t.priority = ?")
            params.append(query["priority"][0])
        if query.get("assignee"):
            clauses.append("t.assignee_id = ?")
            params.append(query["assignee"][0])
        if query.get("search"):
            clauses.append("(LOWER(t.title) LIKE ? OR LOWER(t.desc) LIKE ?)")
            term = f"%{query['search'][0].lower()}%"
            params.extend([term, term])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    order = "date(t.due) ASC"
    if query and query.get("sort", ["due"])[0] == "priority":
        order = "CASE t.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END ASC"
    if query and query.get("sort", ["due"])[0] == "name":
        order = "LOWER(t.title) ASC"
    sql += f" ORDER BY {order}"
    tasks = [dict(row) for row in db.execute(sql, params)]
    for task in tasks:
        task["pid"] = task.pop("project_id")
        task["pri"] = task.pop("priority")
        task["who"] = task.pop("assignee_id") or ""
        task["tags"] = [row["tag"] for row in db.execute("SELECT tag FROM task_tags WHERE task_id = ? ORDER BY tag", (task["id"],))]
        task["comments"] = [dict(row) for row in db.execute("SELECT * FROM comments WHERE task_id = ? ORDER BY created_at", (task["id"],))]
    if task_id:
        return tasks[0] if tasks else None
    return tasks


class Handler(BaseHTTPRequestHandler):
    server_version = "NexusServer/1.0"

    def end_headers(self) -> None:
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin or "*")
        if origin:
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CSRF-Token")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' http://127.0.0.1:8000; img-src 'self' data:; base-uri 'self'; frame-ancestors 'none'")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_file(INDEX_PATH, "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/static/"):
            self.send_static(parsed.path)
            return
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed.path, parse_qs(parsed.query))
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        self.handle_write("POST")

    def do_PUT(self) -> None:
        self.handle_write("PUT")

    def do_DELETE(self) -> None:
        self.handle_write("DELETE")

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")

    def send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(404, "Missing file")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_static(self, request_path: str) -> None:
        relative = request_path.removeprefix("/static/").replace("/", "\\")
        path = (STATIC_ROOT / relative).resolve()
        if not str(path).startswith(str(STATIC_ROOT.resolve())):
            self.send_error(403, "Forbidden")
            return
        content_type = "application/octet-stream"
        if path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        self.send_file(path, content_type)

    def json(self, data, status: int = 200, headers: dict | None = None) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError("request body is too large")
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def handle_api_get(self, path: str, query: dict) -> None:
        with connect() as db:
            user = self.current_user(db)
            if path == "/api/auth/me":
                self.json({"user": public_user(user) if user else None, "csrf": self.current_csrf(db) if user else None})
                return
            if not user:
                self.json({"error": "Authentication required"}, 401)
                return
            if path == "/api/bootstrap":
                self.json(
                    {
                        "user": public_user(user),
                        "csrf": self.current_csrf(db),
                        "team": [dict(row) for row in db.execute("SELECT * FROM team ORDER BY name")],
                        "projects": project_payload(db),
                        "tasks": task_payload(db, query=query),
                        "notifications": [dict(row) for row in db.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT 30")],
                    }
                )
                return
            if path == "/api/stats":
                today = date.today().isoformat()
                total = db.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
                done = db.execute("SELECT COUNT(*) c FROM tasks WHERE status = 'done'").fetchone()["c"]
                self.json(
                    {
                        "total": total,
                        "done": done,
                        "progress": db.execute("SELECT COUNT(*) c FROM tasks WHERE status = 'progress'").fetchone()["c"],
                        "review": db.execute("SELECT COUNT(*) c FROM tasks WHERE status = 'review'").fetchone()["c"],
                        "todo": db.execute("SELECT COUNT(*) c FROM tasks WHERE status = 'todo'").fetchone()["c"],
                        "overdue": db.execute("SELECT COUNT(*) c FROM tasks WHERE status != 'done' AND due < ?", (today,)).fetchone()["c"],
                        "activeProjects": db.execute("SELECT COUNT(*) c FROM projects WHERE status = 'active'").fetchone()["c"],
                    }
                )
                return
            if path == "/api/projects":
                self.json(project_payload(db))
                return
            if path == "/api/tasks":
                self.json(task_payload(db, query=query))
                return
            if path == "/api/team":
                self.json([dict(row) for row in db.execute("SELECT * FROM team ORDER BY name")])
                return
            if path == "/api/notifications":
                self.json([dict(row) for row in db.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT 30")])
                return
        self.send_error(404, "Unknown API endpoint")

    def handle_write(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.strip("/").split("/")
        if not path or path[0] != "api":
            self.send_error(404, "Unknown endpoint")
            return
        try:
            with connect() as db:
                data = self.body() if method in {"POST", "PUT"} else {}
                auth_result = self.handle_auth_write(db, method, path[1:], data)
                if auth_result is not None:
                    return
                if not self.current_user(db):
                    self.json({"error": "Authentication required"}, 401)
                    return
                if not self.valid_csrf(db):
                    self.json({"error": "Invalid security token. Refresh and try again."}, 403)
                    return
                result = self.dispatch_write(db, method, path[1:], data)
                self.json(result)
        except ValueError as exc:
            self.json({"error": str(exc)}, 400)
        except sqlite3.IntegrityError as exc:
            self.json({"error": str(exc)}, 400)

    def current_user(self, db: sqlite3.Connection) -> sqlite3.Row | None:
        cookie_header = self.headers.get("Cookie", "")
        cookie = SimpleCookie(cookie_header)
        morsel = cookie.get("nexus_session")
        if not morsel:
            return None
        token = morsel.value
        row = db.execute(
            """
            SELECT u.*
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, iso_now()),
        ).fetchone()
        if not row:
            db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return row

    def current_session(self, db: sqlite3.Connection) -> sqlite3.Row | None:
        cookie_header = self.headers.get("Cookie", "")
        morsel = SimpleCookie(cookie_header).get("nexus_session")
        if not morsel:
            return None
        return db.execute(
            "SELECT * FROM sessions WHERE token = ? AND expires_at > ?",
            (morsel.value, iso_now()),
        ).fetchone()

    def current_csrf(self, db: sqlite3.Connection) -> str | None:
        session = self.current_session(db)
        return session["csrf_token"] if session else None

    def valid_csrf(self, db: sqlite3.Connection) -> bool:
        session = self.current_session(db)
        if not session or not session["csrf_token"]:
            return False
        sent = self.headers.get("X-CSRF-Token", "")
        return hmac_compare(sent, session["csrf_token"])

    def session_cookie(self, token: str, expires: datetime) -> str:
        return (
            "nexus_session="
            + token
            + f"; Path=/; HttpOnly; SameSite=Strict; Expires={expires.strftime('%a, %d %b %Y %H:%M:%S GMT')}"
        )

    def clear_session_cookie(self) -> str:
        return "nexus_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"

    def handle_auth_write(self, db: sqlite3.Connection, method: str, path: list[str], data: dict) -> bool | None:
        if not path or path[0] != "auth":
            return None
        action = path[1] if len(path) > 1 else ""
        if method == "POST" and action == "login":
            if not self.allow_auth_attempt("login"):
                self.json({"error": "Too many login attempts. Wait a minute and try again."}, 429)
                return True
            email = validate_email(required(data, "email"))
            password = required(data, "password")
            user = db.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email,)).fetchone()
            if not user or not verify_password(password, user["password_hash"]):
                self.json({"error": "Invalid email or password"}, 401)
                return True
            token, expires, csrf = create_session(db, user["id"])
            self.json({"user": public_user(user), "csrf": csrf}, headers={"Set-Cookie": self.session_cookie(token, expires)})
            return True
        if method == "POST" and action == "register":
            if not self.allow_auth_attempt("register"):
                self.json({"error": "Too many signup attempts. Wait a minute and try again."}, 429)
                return True
            name = required(data, "name")
            email = validate_email(required(data, "email"))
            password = required(data, "password")
            if len(password) < 6:
                raise ValueError("password must be at least 6 characters")
            user_id = next_id(db, "u")
            db.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                (user_id, name, email, hash_password(password), iso_now()),
            )
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            token, expires, csrf = create_session(db, user_id)
            self.json({"user": public_user(user), "csrf": csrf}, headers={"Set-Cookie": self.session_cookie(token, expires)})
            return True
        if method == "POST" and action == "logout":
            if self.current_user(db) and not self.valid_csrf(db):
                self.json({"error": "Invalid security token. Refresh and try again."}, 403)
                return True
            cookie_header = self.headers.get("Cookie", "")
            morsel = SimpleCookie(cookie_header).get("nexus_session")
            if morsel:
                db.execute("DELETE FROM sessions WHERE token = ?", (morsel.value,))
            self.json({"ok": True}, headers={"Set-Cookie": self.clear_session_cookie()})
            return True
        raise ValueError("Unsupported auth operation")

    def allow_auth_attempt(self, action: str) -> bool:
        ip = self.client_address[0] if self.client_address else "unknown"
        key = (ip, action)
        now = time.time()
        attempts = [ts for ts in RATE_LIMITS.get(key, []) if now - ts < AUTH_WINDOW_SECONDS]
        attempts.append(now)
        RATE_LIMITS[key] = attempts
        return len(attempts) <= AUTH_MAX_ATTEMPTS

    def dispatch_write(self, db: sqlite3.Connection, method: str, path: list[str], data: dict):
        resource = path[0] if path else ""
        item_id = path[1] if len(path) > 1 else ""

        if resource == "projects":
            if method == "POST":
                name = required(data, "name")
                project_id = next_id(db, "p")
                db.execute(
                    "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
                    (project_id, name, optional_text(data, "desc"), data.get("color", "#E8A030"), data.get("status", "active"), date.today().isoformat()),
                )
                replace_members(db, project_id, data.get("members", []))
                add_notification(db, f"Created project {name}", data.get("color", "#E8A030"))
                return project_payload(db, project_id)
            if method == "PUT" and item_id:
                required(data, "name")
                db.execute(
                    "UPDATE projects SET name = ?, desc = ?, color = ?, status = ? WHERE id = ?",
                    (data["name"], optional_text(data, "desc"), data.get("color", "#E8A030"), data.get("status", "active"), item_id),
                )
                replace_members(db, item_id, data.get("members", []))
                add_notification(db, f"Updated project {data['name']}", data.get("color", "#E8A030"))
                return project_payload(db, item_id)
            if method == "DELETE" and item_id:
                db.execute("DELETE FROM projects WHERE id = ?", (item_id,))
                add_notification(db, "Deleted a project", "#F87171")
                return {"ok": True}

        if resource == "tasks":
            if len(path) == 3 and path[2] == "comments" and method == "POST":
                text = required(data, "text")[:1000]
                db.execute(
                    "INSERT INTO comments VALUES (?, ?, ?, ?, ?)",
                    (next_id(db, "c"), item_id, data.get("member_id", "t1"), text, datetime.utcnow().isoformat()),
                )
                title = db.execute("SELECT title FROM tasks WHERE id = ?", (item_id,)).fetchone()
                add_notification(db, f"Alex commented on {title['title'] if title else 'a task'}", "#C084FC")
                return task_payload(db, item_id)
            if method == "POST":
                task_id = next_id(db, "k")
                save_task(db, task_id, data, create=True)
                add_notification(db, f"Created task {data['title']}", "#E8A030")
                return task_payload(db, task_id)
            if method == "PUT" and item_id:
                save_task(db, item_id, data, create=False)
                add_notification(db, f"Updated task {data['title']}", "#38BDF8")
                return task_payload(db, item_id)
            if method == "DELETE" and item_id:
                db.execute("DELETE FROM tasks WHERE id = ?", (item_id,))
                add_notification(db, "Deleted a task", "#F87171")
                return {"ok": True}

        if resource == "team":
            if method == "POST":
                name = required(data, "name")
                member_id = next_id(db, "t")
                db.execute(
                    "INSERT INTO team VALUES (?, ?, ?, ?, ?)",
                    (member_id, name, required(data, "role"), optional_text(data, "email", 240), data.get("color", "linear-gradient(135deg,#E8A030,#C4862A)")),
                )
                return dict(db.execute("SELECT * FROM team WHERE id = ?", (member_id,)).fetchone())
            if method == "PUT" and item_id:
                db.execute(
                    "UPDATE team SET name = ?, role = ?, email = ?, color = ? WHERE id = ?",
                    (required(data, "name"), required(data, "role"), optional_text(data, "email", 240), data.get("color", ""), item_id),
                )
                return dict(db.execute("SELECT * FROM team WHERE id = ?", (item_id,)).fetchone())
            if method == "DELETE" and item_id:
                db.execute("DELETE FROM team WHERE id = ?", (item_id,))
                return {"ok": True}

        if resource == "notifications" and len(path) > 1 and path[1] == "read" and method == "POST":
            db.execute("UPDATE notifications SET is_read = 1")
            return {"ok": True}

        raise ValueError("Unsupported API operation")


def required(data: dict, key: str) -> str:
    value = str(data.get(key, "")).strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value[:240]


def optional_text(data: dict, key: str, limit: int = 2000) -> str:
    return str(data.get(key, "")).strip()[:limit]


def validate_email(email: str) -> str:
    email = email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError("enter a valid email address")
    return email


def replace_members(db: sqlite3.Connection, project_id: str, members: list[str]) -> None:
    db.execute("DELETE FROM project_members WHERE project_id = ?", (project_id,))
    db.executemany("INSERT OR IGNORE INTO project_members VALUES (?, ?)", [(project_id, member_id) for member_id in members])


def save_task(db: sqlite3.Connection, task_id: str, data: dict, create: bool) -> None:
    title = required(data, "title")
    project_id = required(data, "pid")
    values = (
        task_id,
        project_id,
        title,
        optional_text(data, "desc"),
        data.get("status", "todo"),
        data.get("pri", "medium"),
        data.get("who") or None,
        data.get("due") or (date.today() + timedelta(days=7)).isoformat(),
    )
    if create:
        db.execute("INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values)
    else:
        db.execute(
            "UPDATE tasks SET project_id = ?, title = ?, desc = ?, status = ?, priority = ?, assignee_id = ?, due = ? WHERE id = ?",
            (project_id, title, optional_text(data, "desc"), data.get("status", "todo"), data.get("pri", "medium"), data.get("who") or None, data.get("due"), task_id),
        )
    db.execute("DELETE FROM task_tags WHERE task_id = ?", (task_id,))
    tags = [str(tag).strip()[:32] for tag in data.get("tags", []) if str(tag).strip()][:8]
    db.executemany("INSERT OR IGNORE INTO task_tags VALUES (?, ?)", [(task_id, tag) for tag in tags])


def main() -> None:
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Nexus full-stack app running at http://127.0.0.1:8000")
    print(f"SQLite database: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
