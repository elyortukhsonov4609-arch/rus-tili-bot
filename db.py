"""Ma'lumotlar bazasi.

Ikki xil rejim:
  • DATABASE_URL berilmagan bo'lsa — SQLite fayl (data/bot.db), kompyuterda ishlatish uchun;
  • DATABASE_URL berilgan bo'lsa — PostgreSQL (masalan, bepul Neon.tech), Render kabi serverlarda.
Kod hamma joyda SQLite uslubidagi «?» belgilaridan foydalanadi, PostgreSQL uchun avtomatik o'giriladi.
"""
import json
import os
from decimal import Decimal
import re
import time
from typing import Any, Optional

import aiosqlite

from config import DB_PATH, DEFAULT_SETTINGS

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_PG = DATABASE_URL.startswith("postgres")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    username TEXT,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending / approved / rejected / blocked
    created_at INTEGER NOT NULL,
    approved_at INTEGER
);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    num INTEGER NOT NULL,
    title TEXT NOT NULL,
    short TEXT NOT NULL,
    is_open INTEGER NOT NULL DEFAULT 1,
    file_id TEXT,
    file_name TEXT
);
CREATE TABLE IF NOT EXISTS lesson_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    html TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lesson_reads (
    user_id INTEGER NOT NULL,
    lesson_id INTEGER NOT NULL,
    read_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, lesson_id)
);
CREATE TABLE IF NOT EXISTS tests (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    lesson_id INTEGER,
    sort INTEGER NOT NULL DEFAULT 100,
    per_attempt INTEGER NOT NULL DEFAULT 30,
    is_open INTEGER NOT NULL DEFAULT 1,
    source TEXT
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    q TEXT NOT NULL,
    options TEXT NOT NULL,
    correct INTEGER NOT NULL,
    explanation TEXT
);
CREATE TABLE IF NOT EXISTS fun_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    q TEXT NOT NULL,
    options TEXT NOT NULL,
    correct INTEGER NOT NULL,
    explanation TEXT
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    test_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    total INTEGER NOT NULL,
    correct INTEGER NOT NULL DEFAULT 0,
    duration REAL,
    status TEXT NOT NULL DEFAULT 'active'     -- active / done / stopped / abandoned
);
CREATE TABLE IF NOT EXISTS answers (
    attempt_id INTEGER NOT NULL,
    pos INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    chosen INTEGER,                            -- asl variant indeksi, javob bermasa NULL
    is_correct INTEGER NOT NULL,
    PRIMARY KEY (attempt_id, pos)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS groups (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    active INTEGER NOT NULL DEFAULT 0,
    added_at INTEGER NOT NULL,
    last_post_at REAL NOT NULL DEFAULT 0,
    post_count INTEGER NOT NULL DEFAULT 0,
    thread_id INTEGER
);
CREATE TABLE IF NOT EXISTS group_polls (
    poll_id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    question_id INTEGER,
    fun_id INTEGER,
    correct INTEGER NOT NULL,
    sent_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS group_scores (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    name TEXT,
    correct INTEGER NOT NULL DEFAULT 0,
    answered INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS group_answers (
    poll_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    question_id INTEGER,
    ok INTEGER NOT NULL,
    PRIMARY KEY (poll_id, user_id)
);
CREATE TABLE IF NOT EXISTS study_groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS group_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    test_id TEXT NOT NULL,
    sent_at REAL NOT NULL,
    n INTEGER NOT NULL,
    kind TEXT
);
CREATE TABLE IF NOT EXISTS daily_log (
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    source TEXT,
    PRIMARY KEY (user_id, day)
);
CREATE TABLE IF NOT EXISTS parents (
    parent_id INTEGER NOT NULL,
    child_id INTEGER NOT NULL,
    name TEXT,
    username TEXT,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (parent_id, child_id)
);
CREATE INDEX IF NOT EXISTS ix_q_test ON questions(test_id);
CREATE INDEX IF NOT EXISTS ix_att_user ON attempts(user_id, test_id);
CREATE INDEX IF NOT EXISTS ix_att_test ON attempts(test_id, status);
"""


PG_SCHEMA = (SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
             .replace("INTEGER", "BIGINT").replace("REAL", "DOUBLE PRECISION"))
ID_TABLES = {"lessons", "lesson_pages", "questions", "fun_questions", "attempts", "group_sessions"}
ALL_TABLES = ["users", "lessons", "lesson_pages", "lesson_reads", "tests", "questions", "fun_questions",
              "attempts", "answers", "settings", "groups", "group_polls", "group_scores", "group_answers",
              "study_groups", "group_sessions", "daily_log", "parents"]

# Keyinroq qo'shilgan ustunlar: (jadval, ustun, SQLite turi). Eski bazalarga avtomatik qo'shiladi.
NEW_COLUMNS = [
    ("groups", "thread_id", "INTEGER"),
    ("users", "group_id", "INTEGER"),
    ("lessons", "group_id", "INTEGER"),
    ("tests", "group_id", "INTEGER"),
    ("groups", "study_group_id", "INTEGER"),
    ("groups", "sched_times", "TEXT"),
    ("groups", "sched_count", "INTEGER"),
    ("groups", "sched_last", "TEXT"),
    ("group_answers", "answered_at", "REAL"),
]

_conn: Optional[aiosqlite.Connection] = None
_pool = None


def _pg_sql(sql: str) -> str:
    n = 0

    def rep(_):
        nonlocal n
        n += 1
        return f"${n}"
    return re.sub(r"\?", rep, sql)


def _clean_dsn(url: str) -> str:
    """Neon bergan manzildagi asyncpg tushunmaydigan parametrlarni olib tashlaydi."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query) if k in ("sslmode", "application_name")]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))


async def connect():
    global _conn, _pool
    if IS_PG:
        import asyncpg
        _pool = await asyncpg.create_pool(_clean_dsn(DATABASE_URL), min_size=1, max_size=5, statement_cache_size=0,
                                          command_timeout=30)
        async with _pool.acquire() as c:
            await c.execute(PG_SCHEMA)
            for table, col, typ in NEW_COLUMNS:
                pg_typ = {"INTEGER": "BIGINT", "REAL": "DOUBLE PRECISION"}.get(typ, typ)
                await c.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {pg_typ}")
            for k, v in DEFAULT_SETTINGS.items():
                await c.execute("INSERT INTO settings(key, value) VALUES($1, $2) ON CONFLICT DO NOTHING", k, v)
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _conn = await aiosqlite.connect(DB_PATH)
    _conn.row_factory = aiosqlite.Row
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.executescript(SCHEMA)
    # eski bazalar uchun yangi ustunlar
    for table, col, typ in NEW_COLUMNS:
        try:
            await _conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        except Exception:  # noqa: BLE001 — ustun allaqachon bor
            pass
    for k, v in DEFAULT_SETTINGS.items():
        await _conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT DO NOTHING", (k, v))
    await _conn.commit()


async def close():
    if _pool:
        await _pool.close()
    if _conn:
        await _conn.close()


def _norm(rec):
    """PostgreSQL qatorini oddiy lug'atga aylantiradi (Decimal -> int/float)."""
    if rec is None:
        return None
    out = {}
    for k, v in rec.items():
        if isinstance(v, Decimal):
            v = int(v) if v == v.to_integral_value() else float(v)
        out[k] = v
    return out


async def fetchone(sql: str, args: tuple = ()):
    if IS_PG:
        async with _pool.acquire() as c:
            return _norm(await c.fetchrow(_pg_sql(sql), *args))
    async with _conn.execute(sql, args) as cur:
        return await cur.fetchone()


async def fetchall(sql: str, args: tuple = ()) -> list:
    if IS_PG:
        async with _pool.acquire() as c:
            return [_norm(r) for r in await c.fetch(_pg_sql(sql), *args)]
    async with _conn.execute(sql, args) as cur:
        return list(await cur.fetchall())


async def execute(sql: str, args: tuple = ()):
    """So'rovni bajaradi. INSERT bo'lsa — yangi qatorning id raqamini qaytaradi."""
    if IS_PG:
        m = re.match(r"\s*INSERT\s+INTO\s+(\w+)", sql, re.I)
        async with _pool.acquire() as c:
            if m and m.group(1).lower() in ID_TABLES and "RETURNING" not in sql.upper():
                return await c.fetchval(_pg_sql(sql) + " RETURNING id", *args)
            await c.execute(_pg_sql(sql), *args)
            return None
    async with _conn.execute(sql, args) as cur:
        last = cur.lastrowid
    await _conn.commit()
    return last


async def dump_json() -> bytes:
    """Butun bazani JSON faylga chiqaradi (zaxira nusxa)."""
    out = {}
    for t in ALL_TABLES:
        out[t] = [dict(r) for r in await fetchall(f"SELECT * FROM {t}")]
    return json.dumps(out, ensure_ascii=False, indent=1, default=str).encode("utf-8")


# ---------------- settings ----------------
# Sozlamalar xotirada saqlanadi: bazaga har safar murojaat qilinmaydi
# (bepul onlayn baza bo'sh turganda «uxlab», limitni tejashi uchun).
_settings: dict[str, str] = {}


async def _load_settings():
    _settings.clear()
    for r in await fetchall("SELECT key, value FROM settings"):
        _settings[r["key"]] = r["value"]


async def get_setting(key: str) -> str:
    if not _settings:
        await _load_settings()
    return _settings.get(key, DEFAULT_SETTINGS.get(key, ""))


async def get_int(key: str) -> int:
    try:
        return int(await get_setting(key))
    except ValueError:
        return int(DEFAULT_SETTINGS[key])


async def set_setting(key: str, value: Any):
    _settings[key] = str(value)
    await execute("INSERT INTO settings(key, value) VALUES(?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


# ---------------- users ----------------
async def get_user(uid: int):
    return await fetchone("SELECT * FROM users WHERE id=?", (uid,))


async def add_user(uid: int, full_name: str, username: Optional[str]):
    await execute("INSERT INTO users(id, full_name, username, status, created_at) VALUES(?,?,?,?,?) "
                  "ON CONFLICT(id) DO UPDATE SET full_name=excluded.full_name, username=excluded.username, "
                  "status='pending', created_at=excluded.created_at",
                  (uid, full_name, username, "pending", int(time.time())))


async def set_user_status(uid: int, status: str):
    await execute("UPDATE users SET status=?, approved_at=? WHERE id=?",
                  (status, int(time.time()) if status == "approved" else None, uid))


# ---------------- questions ----------------
def q_from_row(row) -> dict:
    return {"id": row["id"], "q": row["q"], "options": json.loads(row["options"]),
            "correct": row["correct"], "explanation": row["explanation"] or ""}


async def test_questions(test_id: str) -> list[dict]:
    rows = await fetchall("SELECT * FROM questions WHERE test_id=? ORDER BY idx", (test_id,))
    return [q_from_row(r) for r in rows]


async def replace_questions(test_id: str, questions: list[dict]):
    await execute("DELETE FROM questions WHERE test_id=?", (test_id,))
    for i, q in enumerate(questions):
        await execute(
            "INSERT INTO questions(test_id, idx, q, options, correct, explanation) VALUES(?,?,?,?,?,?)",
            (test_id, i, q["q"], json.dumps(q["options"], ensure_ascii=False), q["correct"],
             q.get("explanation", "")))


# ---------------- results / ranking ----------------
async def ranking(test_id: str, mode: str) -> list:
    """Har bir o'quvchidan bitta natija (birinchi yoki eng yaxshi), saralangan."""
    if mode == "best":
        pick = ("ROW_NUMBER() OVER (PARTITION BY a.user_id "
                "ORDER BY CAST(a.correct AS REAL)/a.total DESC, a.duration ASC)")
    else:
        pick = "ROW_NUMBER() OVER (PARTITION BY a.user_id ORDER BY a.finished_at ASC)"
    sql = f"""
    SELECT * FROM (
        SELECT a.*, u.full_name, {pick} AS rn
        FROM attempts a JOIN users u ON u.id = a.user_id
        WHERE a.test_id = ? AND a.status = 'done'
    ) ranked WHERE rn = 1
    ORDER BY CAST(correct AS REAL)/total DESC, duration ASC
    """
    return await fetchall(sql, (test_id,))


# ---------------- o'quv guruhlari (Katta / Kichik) ----------------
DEFAULT_GROUPS = [(1, "Katta guruh", 1), (2, "Kichik guruh", 2)]


async def migrate():
    """Guruhlar paydo bo'lishidan oldingi ma'lumotlarni «Katta guruh»ga biriktiradi (har ishga tushganda xavfsiz)."""
    for gid, name, sort in DEFAULT_GROUPS:
        await execute("INSERT INTO study_groups(id, name, sort) VALUES(?,?,?) ON CONFLICT DO NOTHING", (gid, name, sort))
    await execute("UPDATE users SET group_id=1 WHERE group_id IS NULL AND status IN ('approved','blocked')")
    await execute("UPDATE lessons SET group_id=1 WHERE group_id IS NULL")
    await execute("UPDATE tests SET group_id=1 WHERE group_id IS NULL")
    await execute("UPDATE groups SET study_group_id=1 WHERE study_group_id IS NULL")
    await execute("UPDATE groups SET sched_count=10 WHERE sched_count IS NULL")


_groups_cache: list = []


async def study_groups() -> list:
    global _groups_cache
    if not _groups_cache:
        _groups_cache = await fetchall("SELECT * FROM study_groups ORDER BY sort, id")
    return _groups_cache


async def group_name(gid) -> str:
    for g in await study_groups():
        if g["id"] == gid:
            return g["name"]
    return "—"


async def user_group(uid: int):
    """O'quvchining guruh raqami (admin uchun None — hammasini ko'radi)."""
    u = await get_user(uid)
    return u["group_id"] if u else None
