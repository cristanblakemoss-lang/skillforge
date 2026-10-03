#!/usr/bin/env python3
"""SkillForge v7 — consumer skill-building product ready for public deployment.

Standard-library only. Designed for local development and easy deployment behind a
TLS reverse proxy. It includes server-side accounts, sessions, CSRF, SQLite,
custom skills, onboarding, analytics events, password recovery hooks, and a
Stripe checkout + webhook integration point.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.server
import json
import mimetypes
import os
import secrets
import sqlite3
import time
import urllib.parse
from email.message import EmailMessage
import smtplib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SKILLFORGE_DB_PATH", str(ROOT / "skillforge.db"))).expanduser()
APP_VERSION = "7.0.0"
SESSION_TTL = int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60 * 24 * 14)))
RECOVERY_TTL = int(os.getenv("RECOVERY_TTL_SECONDS", str(60 * 30)))
DEV_MODE = os.getenv("SKILLFORGE_DEV", "1") == "1"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
STRIPE_PAYMENT_LINK = os.getenv("STRIPE_PAYMENT_LINK", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

CORE_SKILLS = [
    ("software", "Software", "BUILD", 28),
    ("writing", "Writing", "WRITE", 0),
    ("design", "Design", "DESIGN", 0),
    ("fitness", "Fitness", "TRAIN", 0),
    ("language", "Language", "SPEAK", 0),
    ("money", "Money", "REVIEW", 0),
]

MISSIONS = [
    ("software", "Ship one tiny interaction", "Build one complete interaction and test it end to end.", "BUILD", 25, 30, "free"),
    ("software", "Refactor one rough function", "Simplify a function, remove duplication, and run the code.", "REFINE", 20, 25, "free"),
    ("software", "Make one page faster", "Find one avoidable delay or expensive operation and improve it.", "OPTIMIZE", 30, 35, "plus"),
    ("writing", "Write 300 useful words", "Explain one idea clearly to a reader who knows nothing about it.", "WRITE", 25, 30, "free"),
    ("writing", "Cut 20% of a draft", "Remove filler while keeping the meaning and voice intact.", "EDIT", 20, 25, "plus"),
    ("design", "Fix one hierarchy problem", "Change one visual hierarchy issue, then compare before and after.", "DESIGN", 30, 30, "free"),
    ("fitness", "Complete a focused session", "Choose a simple workout and finish without multitasking.", "TRAIN", 30, 30, "free"),
    ("language", "Speak for five minutes", "Talk about your day without switching languages.", "SPEAK", 15, 20, "free"),
    ("money", "Audit one spending pattern", "Review recent spending and identify one recurring behavior.", "REVIEW", 20, 25, "free"),
]

CHALLENGES = [
    ("seven_reps", "Seven deliberate reps", "Complete seven practice sessions on one skill.", 7, 100, "STARTER", "free"),
    ("proof_week", "Proof every day", "Save one piece of evidence for five separate practice days.", 5, 120, "EVIDENCE", "plus"),
    ("fifty_minutes", "Fifty focused minutes", "Log fifty intentional minutes within seven days.", 7, 90, "FOCUS", "free"),
    ("ship_something", "Ship something", "Create and finish a small artifact instead of endlessly preparing.", 3, 150, "SHIP", "plus"),
]

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  plan TEXT NOT NULL DEFAULT 'free',
  email_verified INTEGER NOT NULL DEFAULT 0,
  onboarding_complete INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS profiles (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  daily_goal INTEGER NOT NULL DEFAULT 25,
  active_skill_id TEXT NOT NULL DEFAULT 'software',
  streak INTEGER NOT NULL DEFAULT 0,
  xp INTEGER NOT NULL DEFAULT 0,
  missions_completed INTEGER NOT NULL DEFAULT 0,
  last_rep_day TEXT
);
CREATE TABLE IF NOT EXISTS skills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  slug TEXT NOT NULL,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  progress INTEGER NOT NULL DEFAULT 0,
  reps INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  UNIQUE(user_id, slug)
);
CREATE TABLE IF NOT EXISTS proof (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  kind TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  minutes INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS challenge_starts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  challenge_id TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(user_id, challenge_id)
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS recovery_tokens (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS analytics_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  properties_json TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_user_created ON events(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_analytics_created ON analytics_events(created_at);
"""


def now() -> int:
    return int(time.time())


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def json_bytes(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def pbkdf2(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
    return "pbkdf2_sha256$260000$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


def check_password(password: str, stored: str) -> bool:
    try:
        algo, rounds_s, salt_s, digest_s = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_s.encode())
        expected = base64.urlsafe_b64decode(digest_s.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds_s))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def clean_name(value: str, limit: int = 60) -> str:
    value = " ".join(str(value or "").strip().split())
    return value[:limit]


def clean_email(value: str) -> str:
    return str(value or "").strip().lower()[:254]


def require_csrf(handler, row) -> bool:
    if not row or not hmac.compare_digest(handler.headers.get("X-CSRF-Token", ""), row["csrf_token"]):
        handler.send_json({"ok": False, "error": "Invalid CSRF token."}, 403)
        return False
    return True


def seed_user(conn: sqlite3.Connection, user_id: int) -> None:
    for slug, name, category, progress in CORE_SKILLS:
        conn.execute(
            "INSERT OR IGNORE INTO skills(user_id,slug,name,category,progress,reps,created_at) VALUES(?,?,?,?,?,?,?)",
            (user_id, slug, name, category, progress, 0, now()),
        )


def create_user(email: str, name: str, password: str) -> int:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if "@" not in email:
        raise ValueError("Enter a valid email address.")
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO users(email,name,password_hash,created_at) VALUES(?,?,?,?)",
            (clean_email(email), clean_name(name) or "Builder", pbkdf2(password), now()),
        )
        user_id = cur.lastrowid
        conn.execute("INSERT INTO profiles(user_id) VALUES(?)", (user_id,))
        seed_user(conn, user_id)
        conn.commit()
        return int(user_id)


def get_session(handler):
    cookie = handler.headers.get("Cookie", "")
    sid = ""
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith("sf_session="):
            sid = part.split("=", 1)[1]
    if not sid:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT s.*, u.email, u.name, u.plan, u.email_verified, u.onboarding_complete FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?",
            (hash_token(sid), now()),
        ).fetchone()
        if row:
            return row
    return None


def new_session(handler, user_id: int):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    created = now()
    expires = created + SESSION_TTL
    with db() as conn:
        conn.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,created_at,expires_at) VALUES(?,?,?,?,?)", (hash_token(token), user_id, csrf, created, expires))
        conn.commit()
    flags = ["HttpOnly", "SameSite=Lax", "Path=/", f"Max-Age={SESSION_TTL}"]
    if COOKIE_SECURE:
        flags.append("Secure")
    handler.extra_headers.append(("Set-Cookie", "sf_session=" + token + "; " + "; ".join(flags)))
    return csrf


def clear_session(handler):
    row = get_session(handler)
    if row:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (row["token_hash"],))
            conn.commit()
    flags = ["HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=0"]
    if COOKIE_SECURE:
        flags.append("Secure")
    handler.extra_headers.append(("Set-Cookie", "sf_session=; " + "; ".join(flags)))


def user_state(user_id: int):
    with db() as conn:
        u = conn.execute("SELECT id,email,name,plan,email_verified,onboarding_complete,created_at FROM users WHERE id=?", (user_id,)).fetchone()
        p = conn.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
        skills = [dict(r) for r in conn.execute("SELECT * FROM skills WHERE user_id=? ORDER BY id", (user_id,)).fetchall()]
        proofs = [dict(r) for r in conn.execute("SELECT * FROM proof WHERE user_id=? ORDER BY created_at DESC LIMIT 100", (user_id,)).fetchall()]
        events = []
        for r in conn.execute("SELECT * FROM events WHERE user_id=? ORDER BY created_at DESC LIMIT 200", (user_id,)).fetchall():
            d = dict(r)
            try: d["payload"] = json.loads(d.pop("payload_json"))
            except Exception: d["payload"] = {}
            events.append(d)
        challenges = [dict(r) for r in conn.execute("SELECT challenge_id,created_at FROM challenge_starts WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()]
    return {
        "user": dict(u) if u else None,
        "profile": dict(p) if p else None,
        "skills": skills,
        "proofs": proofs,
        "events": events,
        "challenges": challenges,
    }


def api_state(handler):
    sess = get_session(handler)
    if not sess:
        handler.send_json({"ok": True, "authenticated": False})
        return
    handler.send_json({"ok": True, "authenticated": True, "csrf": sess["csrf_token"], "state": user_state(sess["user_id"])})


def add_event(user_id, event_type, payload=None, minutes=0):
    with db() as conn:
        conn.execute("INSERT INTO events(user_id,type,payload_json,minutes,created_at) VALUES(?,?,?,?,?)", (user_id, event_type, json.dumps(payload or {}, separators=(",", ":")), int(minutes or 0), now()))
        conn.commit()


def analytics(user_id, name, props=None):
    with db() as conn:
        conn.execute("INSERT INTO analytics_events(user_id,name,properties_json,created_at) VALUES(?,?,?,?)", (user_id, name, json.dumps(props or {}, separators=(",", ":")), now()))
        conn.commit()


def update_rep(user_id, skill_id, minutes, xp, mission_name):
    day = time.strftime("%Y-%m-%d", time.localtime())
    with db() as conn:
        p = conn.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
        streak = p["streak"]
        if p["last_rep_day"] != day:
            if p["last_rep_day"]:
                try:
                    prev = time.strptime(p["last_rep_day"], "%Y-%m-%d")
                    now_tm = time.strptime(day, "%Y-%m-%d")
                    # Date distance using epoch seconds.
                    delta = int(time.mktime(now_tm) - time.mktime(prev)) // 86400
                except Exception:
                    delta = 999
                streak = streak + 1 if delta == 1 else 1
            else:
                streak = 1
        else:
            streak = max(1, streak)
        conn.execute("UPDATE profiles SET xp=xp+?,missions_completed=missions_completed+1,streak=?,last_rep_day=? WHERE user_id=?", (xp, streak, day, user_id))
        conn.execute("UPDATE skills SET reps=reps+1,progress=MIN(100,progress+?) WHERE id=? AND user_id=?", (max(1, minutes // 3), skill_id, user_id))
        conn.execute("INSERT INTO events(user_id,type,payload_json,minutes,created_at) VALUES(?,?,?,?,?)", (user_id, "mission_complete", json.dumps({"mission": mission_name, "xp": xp, "skill_id": skill_id}), minutes, now()))
        conn.commit()


def send_recovery_email(to_email: str, token: str) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    from_email = os.getenv("SMTP_FROM", username).strip()
    base = os.getenv("APP_ORIGIN", "http://127.0.0.1:3010").rstrip("/")
    link = f"{base}/#reset?token={urllib.parse.quote(token)}"
    if not host or not from_email:
        return False
    msg = EmailMessage()
    msg["Subject"] = "Reset your SkillForge password"
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content("Reset your SkillForge password:\n\n" + link + "\n\nThis link expires soon.")
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(msg)
    return True


def stripe_signature_valid(payload: bytes, signature: str, secret: str) -> bool:
    # Stripe-Signature: t=timestamp,v1=signature,...
    pieces = {}
    for item in signature.split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            pieces.setdefault(k, []).append(v)
    try:
        ts = int(pieces.get("t", ["0"])[0])
        if abs(time.time() - ts) > 300:
            return False
        signed = f"{ts}.".encode() + payload
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(expected, v) for v in pieces.get("v1", []))
    except Exception:
        return False


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.extra_headers = []

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")

    def headers_common(self):
        return [
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "same-origin"),
            ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
            ("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self'; connect-src 'self'"),
        ]

    def send_bytes(self, body: bytes, status=200, ctype="application/octet-stream"):
        self.send_response(status)
        for k, v in self.headers_common() + self.extra_headers:
            self.send_header(k, v)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.extra_headers.clear()

    def send_json(self, obj, status=200):
        self.send_bytes(json_bytes(obj), status, "application/json; charset=utf-8")

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 512 * 1024:
            raise ValueError("Request body is too large.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ValueError("Invalid JSON body.")
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object.")
        return data

    def require_auth(self, csrf=True):
        sess = get_session(self)
        if not sess:
            self.send_json({"ok": False, "error": "Authentication required."}, 401)
            return None
        if csrf and not require_csrf(self, sess):
            return None
        return sess

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/health":
            self.send_json({"ok": True, "version": APP_VERSION, "time": now()}); return
        if path == "/api/me":
            api_state(self); return
        if path == "/api/catalog":
            self.send_json({"ok": True, "skills": CORE_SKILLS, "missions": [list(m) for m in MISSIONS], "challenges": [list(c) for c in CHALLENGES]}); return
        if path == "/api/challenges":
            self.send_json({"ok": True, "challenges": [{"id":a,"name":b,"desc":c,"days":d,"reward":e,"difficulty":f,"plan":g} for a,b,c,d,e,f,g in CHALLENGES]}); return
        if path == "/api/recovery/status":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            token = (q.get("token") or [""])[0]
            valid = False
            if token:
                with db() as conn:
                    row = conn.execute("SELECT id FROM recovery_tokens WHERE token_hash=? AND used=0 AND expires_at>?", (hash_token(token), now())).fetchone()
                    valid = bool(row)
            self.send_json({"ok": True, "valid": valid}); return
        if path.startswith("/api/"):
            self.send_json({"ok": False, "error": "Not found."}, 404); return
        self.serve_static(path)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        # Stripe sends signed webhook requests without a SkillForge user session.
        # Verify the exact raw body before parsing JSON.
        if path == "/api/stripe/webhook":
            if not STRIPE_WEBHOOK_SECRET:
                self.send_json({"ok": False, "error": "Stripe webhook secret is not configured."}, 503); return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length > 512 * 1024:
                    raise ValueError("Request body is too large.")
                raw = self.rfile.read(length) if length else b"{}"
                if not stripe_signature_valid(raw, self.headers.get("Stripe-Signature", ""), STRIPE_WEBHOOK_SECRET):
                    self.send_json({"ok": False, "error": "Invalid Stripe signature."}, 400); return
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("Webhook body must be a JSON object.")
                event_type = str(data.get("type") or "")
                obj = (((data.get("data") or {}).get("object")) or {})
                email = clean_email(obj.get("customer_email") or obj.get("email") or "")
                if email:
                    with db() as conn:
                        if event_type in {"checkout.session.completed", "customer.subscription.created", "customer.subscription.updated"}:
                            conn.execute("UPDATE users SET plan='plus' WHERE email=?", (email,))
                        elif event_type in {"customer.subscription.deleted"}:
                            conn.execute("UPDATE users SET plan='free' WHERE email=?", (email,))
                        conn.commit()
                return self.send_json({"ok": True})
            except ValueError as e:
                self.send_json({"ok": False, "error": str(e)}, 400); return
            except Exception as e:
                print("WEBHOOK ERROR", repr(e))
                self.send_json({"ok": False, "error": "Webhook processing failed."}, 500); return
        try:
            data = self.read_json()
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400); return

        try:
            if path == "/api/register":
                email = clean_email(data.get("email")); name = clean_name(data.get("name")); password = str(data.get("password") or "")
                user_id = create_user(email, name, password)
                csrf = new_session(self, user_id)
                analytics(user_id, "account_created", {})
                self.send_json({"ok": True, "csrf": csrf, "state": user_state(user_id)}); return

            if path == "/api/demo":
                email = "demo@skillforge.local"
                with db() as conn:
                    row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
                if row:
                    user_id = int(row["id"])
                else:
                    user_id = create_user(email, "Demo Builder", "demo-password-2026")
                    with db() as conn:
                        conn.execute("UPDATE users SET email_verified=1,onboarding_complete=1 WHERE id=?", (user_id,)); conn.commit()
                csrf = new_session(self, user_id)
                analytics(user_id, "demo_started", {})
                self.send_json({"ok": True, "csrf": csrf, "state": user_state(user_id)}); return

            if path == "/api/login":
                email = clean_email(data.get("email")); password = str(data.get("password") or "")
                with db() as conn:
                    row = conn.execute("SELECT id,password_hash FROM users WHERE email=?", (email,)).fetchone()
                if not row or not check_password(password, row["password_hash"]):
                    self.send_json({"ok": False, "error": "Email or password is incorrect."}, 401); return
                csrf = new_session(self, row["id"])
                analytics(row["id"], "login", {})
                self.send_json({"ok": True, "csrf": csrf, "state": user_state(row["id"])}); return

            if path == "/api/logout":
                sess = self.require_auth(csrf=True)
                if sess: analytics(sess["user_id"], "logout", {}); clear_session(self); self.send_json({"ok": True})
                return

            if path == "/api/recovery/request":
                email = clean_email(data.get("email"))
                with db() as conn:
                    user = conn.execute("SELECT id,email FROM users WHERE email=?", (email,)).fetchone()
                    if user:
                        token = secrets.token_urlsafe(32)
                        conn.execute("INSERT INTO recovery_tokens(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)", (hash_token(token), user["id"], now(), now() + RECOVERY_TTL))
                        conn.commit()
                        try:
                            sent = send_recovery_email(user["email"], token)
                        except Exception:
                            sent = False
                        response = {"ok": True, "message": "If the account exists, recovery instructions were prepared."}
                        if DEV_MODE and not sent:
                            response["dev_recovery_token"] = token
                        self.send_json(response); return
                self.send_json({"ok": True, "message": "If the account exists, recovery instructions were prepared."}); return

            if path == "/api/recovery/reset":
                token = str(data.get("token") or ""); password = str(data.get("password") or "")
                if len(password) < 8 or not token:
                    self.send_json({"ok": False, "error": "A valid token and an 8+ character password are required."}, 400); return
                with db() as conn:
                    row = conn.execute("SELECT user_id FROM recovery_tokens WHERE token_hash=? AND used=0 AND expires_at>?", (hash_token(token), now())).fetchone()
                    if not row:
                        self.send_json({"ok": False, "error": "Recovery token is invalid or expired."}, 400); return
                    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (pbkdf2(password), row["user_id"]))
                    conn.execute("UPDATE recovery_tokens SET used=1 WHERE token_hash=?", (hash_token(token),))
                    conn.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
                    conn.commit()
                self.send_json({"ok": True, "message": "Password reset. Sign in with the new password."}); return

            sess = self.require_auth(csrf=True)
            if not sess:
                return
            user_id = int(sess["user_id"])

            if path == "/api/onboarding":
                active = clean_name(data.get("activeSkill"), 40).lower().replace(" ", "-") or "software"
                goal = max(5, min(240, int(data.get("dailyGoal") or 25)))
                name = clean_name(data.get("name"), 60)
                with db() as conn:
                    if name:
                        conn.execute("UPDATE users SET name=?,onboarding_complete=1 WHERE id=?", (name, user_id))
                    else:
                        conn.execute("UPDATE users SET onboarding_complete=1 WHERE id=?", (user_id,))
                    conn.execute("UPDATE profiles SET active_skill_id=?,daily_goal=? WHERE user_id=?", (active, goal, user_id))
                    conn.commit()
                analytics(user_id, "onboarding_completed", {"active_skill": active, "daily_goal": goal})
                self.send_json({"ok": True, "state": user_state(user_id)}); return

            if path == "/api/profile":
                fields = []
                vals = []
                if "activeSkill" in data:
                    skill = str(data["activeSkill"])[:80]
                    with db() as conn:
                        exists = conn.execute("SELECT 1 FROM skills WHERE user_id=? AND slug=?", (user_id, skill)).fetchone()
                    if not exists:
                        self.send_json({"ok": False, "error": "Unknown skill."}, 400); return
                    fields.append("active_skill_id=?"); vals.append(skill)
                if "dailyGoal" in data:
                    fields.append("daily_goal=?"); vals.append(max(5, min(240, int(data["dailyGoal"]))))
                if fields:
                    with db() as conn:
                        conn.execute(f"UPDATE profiles SET {','.join(fields)} WHERE user_id=?", (*vals, user_id)); conn.commit()
                analytics(user_id, "profile_updated", {k:data[k] for k in ("activeSkill","dailyGoal") if k in data})
                self.send_json({"ok": True, "state": user_state(user_id)}); return

            if path == "/api/skill":
                action = data.get("action", "create")
                if action == "create":
                    name = clean_name(data.get("name"), 60)
                    if len(name) < 2:
                        self.send_json({"ok": False, "error": "Skill name is too short."}, 400); return
                    slug = "custom-" + secrets.token_hex(6)
                    category = clean_name(data.get("category"), 30).upper() or "CUSTOM"
                    with db() as conn:
                        conn.execute("INSERT INTO skills(user_id,slug,name,category,progress,reps,created_at) VALUES(?,?,?,?,0,0,?)", (user_id, slug, name, category, now())); conn.commit()
                    analytics(user_id, "skill_created", {"category": category})
                    self.send_json({"ok": True, "state": user_state(user_id)}); return
                if action == "delete":
                    skill_id = int(data.get("id") or 0)
                    with db() as conn:
                        active = conn.execute("SELECT active_skill_id FROM profiles WHERE user_id=?", (user_id,)).fetchone()
                        target = conn.execute("SELECT slug FROM skills WHERE id=? AND user_id=?", (skill_id,user_id)).fetchone()
                        if not target:
                            self.send_json({"ok": False, "error": "Skill not found."}, 404); return
                        count = conn.execute("SELECT COUNT(*) AS c FROM skills WHERE user_id=?", (user_id,)).fetchone()["c"]
                        if count <= 1:
                            self.send_json({"ok": False, "error": "Keep at least one skill."}, 400); return
                        conn.execute("DELETE FROM skills WHERE id=? AND user_id=?", (skill_id,user_id))
                        if active["active_skill_id"] == target["slug"]:
                            fallback = conn.execute("SELECT slug FROM skills WHERE user_id=? ORDER BY id LIMIT 1", (user_id,)).fetchone()["slug"]
                            conn.execute("UPDATE profiles SET active_skill_id=? WHERE user_id=?", (fallback,user_id))
                        conn.commit()
                    analytics(user_id, "skill_deleted", {})
                    self.send_json({"ok": True, "state": user_state(user_id)}); return

            if path == "/api/mission/complete":
                skill_id = int(data.get("skillId") or 0)
                minutes = max(1, min(480, int(data.get("minutes") or 1)))
                xp = max(1, min(500, int(data.get("xp") or 1)))
                mission_name = clean_name(data.get("mission"), 120)
                with db() as conn:
                    exists = conn.execute("SELECT 1 FROM skills WHERE id=? AND user_id=?", (skill_id,user_id)).fetchone()
                if not exists:
                    self.send_json({"ok": False, "error": "Skill not found."}, 404); return
                update_rep(user_id, skill_id, minutes, xp, mission_name)
                analytics(user_id, "mission_completed", {"skill_id": skill_id, "minutes": minutes, "xp": xp})
                self.send_json({"ok": True, "state": user_state(user_id)}); return

            if path == "/api/time":
                minutes = max(1, min(480, int(data.get("minutes") or 1)))
                skill_id = str(data.get("skillId") or "")[:80]
                add_event(user_id, "practice_log", {"skill_id": skill_id}, minutes)
                analytics(user_id, "practice_logged", {"minutes": minutes})
                self.send_json({"ok": True, "state": user_state(user_id)}); return

            if path == "/api/proof":
                title = clean_name(data.get("title"), 120)
                kind = clean_name(data.get("kind"), 30).upper() or "NOTE"
                note = clean_name(data.get("note"), 500)
                if len(title) < 2:
                    self.send_json({"ok": False, "error": "Proof needs a title."}, 400); return
                with db() as conn:
                    conn.execute("INSERT INTO proof(user_id,title,kind,note,created_at) VALUES(?,?,?,?,?)", (user_id,title,kind,note,now())); conn.commit()
                analytics(user_id, "proof_saved", {"kind": kind})
                self.send_json({"ok": True, "state": user_state(user_id)}); return

            if path == "/api/proof/delete":
                proof_id = int(data.get("id") or 0)
                with db() as conn:
                    conn.execute("DELETE FROM proof WHERE id=? AND user_id=?", (proof_id,user_id)); conn.commit()
                analytics(user_id, "proof_deleted", {})
                self.send_json({"ok": True, "state": user_state(user_id)}); return

            if path == "/api/challenge/start":
                challenge_id = str(data.get("id") or "")[:80]
                match = next((c for c in CHALLENGES if c[0] == challenge_id), None)
                if not match:
                    self.send_json({"ok": False, "error": "Challenge not found."}, 404); return
                if match[6] == "plus" and sess["plan"] != "plus":
                    self.send_json({"ok": False, "error": "This challenge is part of Forge+."}, 402); return
                with db() as conn:
                    conn.execute("INSERT OR IGNORE INTO challenge_starts(user_id,challenge_id,created_at) VALUES(?,?,?)", (user_id,challenge_id,now())); conn.commit()
                analytics(user_id, "challenge_started", {"challenge_id": challenge_id})
                self.send_json({"ok": True, "state": user_state(user_id)}); return

            if path == "/api/analytics":
                name = clean_name(data.get("name"), 80)
                props = data.get("properties") if isinstance(data.get("properties"), dict) else {}
                if name:
                    analytics(user_id, name, props)
                self.send_json({"ok": True}); return

            if path == "/api/export":
                self.send_json({"ok": True, "exported_at": now(), "state": user_state(user_id)}); return

            if path == "/api/checkout":
                if not STRIPE_PAYMENT_LINK:
                    self.send_json({"ok": False, "error": "Checkout is not configured yet. Set STRIPE_PAYMENT_LINK on the server."}, 503); return
                analytics(user_id, "checkout_opened", {"plan": "plus"})
                self.send_json({"ok": True, "url": STRIPE_PAYMENT_LINK}); return

            self.send_json({"ok": False, "error": "Not found."}, 404)
        except sqlite3.IntegrityError as e:
            msg = "That account already exists." if path == "/api/register" else "A database constraint was hit."
            self.send_json({"ok": False, "error": msg}, 409)
        except Exception as e:
            print("ERROR", path, repr(e))
            self.send_json({"ok": False, "error": "Server error."}, 500)

    def serve_static(self, path):
        rel = urllib.parse.unquote(path.lstrip("/"))
        if not rel:
            rel = "index.html"
        target = (ROOT / rel).resolve()
        if ROOT not in target.parents and target != ROOT:
            self.send_json({"ok": False, "error": "Not found."}, 404); return
        if not target.is_file():
            self.send_json({"ok": False, "error": "Not found."}, 404); return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_bytes(target.read_bytes(), 200, ctype + ("; charset=utf-8" if ctype.startswith("text/") or ctype.endswith("javascript") else ""))


def main():
    global DB_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "3010")))
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--db", default=os.getenv("SKILLFORGE_DB_PATH", str(DB_PATH)))
    args = parser.parse_args()
    DB_PATH = Path(args.db).expanduser().resolve()
    init_db()
    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"SkillForge v{APP_VERSION} → listening on {args.host}:{args.port}")
    print(f"Database → {DB_PATH}")
    print("Production notes: use HTTPS, a reverse proxy, managed PostgreSQL, backups, and a real email provider before public launch.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
