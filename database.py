from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("VOZLOCAL_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "vozlocal.sqlite3"
SESSION_DAYS = max(1, min(90, int(os.getenv("VOZLOCAL_SESSION_DAYS", "14"))))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(DB_PATH, timeout=30)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys = ON")
    database.execute("PRAGMA journal_mode = WAL")
    try:
        yield database
        database.commit()
    finally:
        database.close()


def initialize_database() -> None:
    with connection() as database:
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user', 'admin')),
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL COLLATE NOCASE,
                teacher TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '#0d6b53',
                is_archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, name)
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL,
                lesson_title TEXT NOT NULL DEFAULT '',
                lesson_date TEXT,
                filename TEXT NOT NULL,
                stored_audio_name TEXT,
                audio_size INTEGER NOT NULL DEFAULT 0,
                audio_deleted INTEGER NOT NULL DEFAULT 0,
                transcript TEXT,
                segments_json TEXT,
                text_deleted INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                error TEXT,
                prompt TEXT NOT NULL DEFAULT '',
                duration_seconds REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);
            CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON jobs(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_courses_user_name ON courses(user_id, name);
            """
        )
        job_columns = {
            row["name"] for row in database.execute("PRAGMA table_info(jobs)").fetchall()
        }
        if "course_id" not in job_columns:
            database.execute(
                "ALTER TABLE jobs ADD COLUMN course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL"
            )
        if "lesson_title" not in job_columns:
            database.execute(
                "ALTER TABLE jobs ADD COLUMN lesson_title TEXT NOT NULL DEFAULT ''"
            )
        if "lesson_date" not in job_columns:
            database.execute("ALTER TABLE jobs ADD COLUMN lesson_date TEXT")
        database.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_course_created ON jobs(course_id, created_at DESC)"
        )
        database.execute(
            """
            UPDATE jobs
            SET status = 'failed', progress = 0,
                message = 'Traitement interrompu par le redémarrage du serveur.',
                error = 'Vous pouvez relancer la transcription depuis le fichier audio conservé.',
                updated_at = ?
            WHERE status IN ('queued', 'loading', 'processing', 'exporting')
            """,
            (utc_now(),),
        )
        database.execute("DELETE FROM sessions WHERE expires_at <= ?", (utc_now(),))


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2**14, 8, 1
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p)
    return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
        )
        return hmac.compare_digest(candidate, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


def create_user(name: str, email: str, password: str) -> dict[str, Any]:
    normalized = normalize_email(email)
    with connection() as database:
        user_count = database.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        role = "admin" if user_count == 0 else "user"
        cursor = database.execute(
            """
            INSERT INTO users (name, email, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name.strip(), normalized, hash_password(password), role, utc_now()),
        )
        row = database.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return public_user(row)


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    with connection() as database:
        row = database.execute(
            "SELECT * FROM users WHERE email = ?", (normalize_email(email),)
        ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return public_user(row)


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(40)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(days=SESSION_DAYS)
    with connection() as database:
        database.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (
                token_hash,
                user_id,
                created_at.isoformat(timespec="seconds"),
                expires_at.isoformat(timespec="seconds"),
            ),
        )
    return token


def user_from_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connection() as database:
        row = database.execute(
            """
            SELECT u.* FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ?
            """,
            (token_hash, utc_now()),
        ).fetchone()
    return public_user(row) if row else None


def revoke_session(token: str) -> None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connection() as database:
        database.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def serialize_course(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "teacher": row["teacher"],
        "color": row["color"],
        "is_archived": bool(row["is_archived"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "job_count": int(row["job_count"] or 0) if "job_count" in keys else 0,
        "completed_count": (
            int(row["completed_count"] or 0) if "completed_count" in keys else 0
        ),
        "latest_job_at": row["latest_job_at"] if "latest_job_at" in keys else None,
    }


def create_course(user_id: int, name: str, teacher: str, color: str) -> dict[str, Any]:
    now = utc_now()
    with connection() as database:
        cursor = database.execute(
            """
            INSERT INTO courses (user_id, name, teacher, color, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, name, teacher, color, now, now),
        )
        row = database.execute(
            "SELECT * FROM courses WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return serialize_course(row)


def get_course(course_id: int, user_id: int) -> dict[str, Any] | None:
    with connection() as database:
        row = database.execute(
            """
            SELECT c.*, COUNT(j.id) AS job_count,
                   SUM(CASE WHEN j.status = 'completed' THEN 1 ELSE 0 END) AS completed_count,
                   MAX(j.created_at) AS latest_job_at
            FROM courses c
            LEFT JOIN jobs j ON j.course_id = c.id
            WHERE c.id = ? AND c.user_id = ?
            GROUP BY c.id
            """,
            (course_id, user_id),
        ).fetchone()
    return serialize_course(row) if row else None


def list_courses(user_id: int, *, include_archived: bool = True) -> list[dict[str, Any]]:
    where = "c.user_id = ?" if include_archived else "c.user_id = ? AND c.is_archived = 0"
    with connection() as database:
        rows = database.execute(
            f"""
            SELECT c.*, COUNT(j.id) AS job_count,
                   SUM(CASE WHEN j.status = 'completed' THEN 1 ELSE 0 END) AS completed_count,
                   MAX(j.created_at) AS latest_job_at
            FROM courses c
            LEFT JOIN jobs j ON j.course_id = c.id
            WHERE {where}
            GROUP BY c.id
            ORDER BY c.is_archived, c.name COLLATE NOCASE
            """,
            (user_id,),
        ).fetchall()
    return [serialize_course(row) for row in rows]


def update_course(course_id: int, user_id: int, **changes: Any) -> dict[str, Any] | None:
    allowed = {"name", "teacher", "color", "is_archived"}
    payload = {key: value for key, value in changes.items() if key in allowed}
    if not payload:
        return get_course(course_id, user_id)
    payload["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in payload)
    with connection() as database:
        cursor = database.execute(
            f"UPDATE courses SET {assignments} WHERE id = ? AND user_id = ?",
            (*payload.values(), course_id, user_id),
        )
    return get_course(course_id, user_id) if cursor.rowcount else None


def delete_course(course_id: int, user_id: int) -> bool:
    with connection() as database:
        cursor = database.execute(
            "DELETE FROM courses WHERE id = ? AND user_id = ?", (course_id, user_id)
        )
    return cursor.rowcount > 0


def insert_job(job: dict[str, Any]) -> None:
    now = utc_now()
    with connection() as database:
        database.execute(
            """
            INSERT INTO jobs (
                id, user_id, course_id, lesson_title, lesson_date, filename,
                stored_audio_name, audio_size, status, progress, message, prompt,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["id"], job["user_id"], job.get("course_id"),
                job.get("lesson_title", ""), job.get("lesson_date"), job["filename"],
                job["stored_audio_name"], job["audio_size"], job["status"],
                job["progress"], job["message"], job.get("prompt", ""), now, now,
            ),
        )


def update_job(job_id: str, **changes: Any) -> None:
    if not changes:
        return
    allowed = {
        "stored_audio_name", "audio_size", "audio_deleted", "transcript", "segments_json",
        "text_deleted", "status", "progress", "message", "error", "duration_seconds",
        "completed_at",
    }
    payload = {key: value for key, value in changes.items() if key in allowed}
    payload["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in payload)
    with connection() as database:
        database.execute(
            f"UPDATE jobs SET {assignments} WHERE id = ?",
            (*payload.values(), job_id),
        )


def serialize_job(row: sqlite3.Row, *, include_text: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row["id"],
        "user_id": int(row["user_id"]),
        "filename": row["filename"],
        "course_id": int(row["course_id"]) if row["course_id"] is not None else None,
        "course_name": row["course_name"] if "course_name" in row.keys() else None,
        "course_color": row["course_color"] if "course_color" in row.keys() else None,
        "lesson_title": row["lesson_title"] or "",
        "lesson_date": row["lesson_date"],
        "status": row["status"],
        "progress": int(row["progress"]),
        "message": row["message"],
        "error": row["error"],
        "duration_seconds": row["duration_seconds"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
        "has_audio": bool(row["stored_audio_name"]) and not bool(row["audio_deleted"]),
        "has_text": bool(row["transcript"]) and not bool(row["text_deleted"]),
        "audio_size": int(row["audio_size"] or 0),
    }
    if "owner_name" in row.keys():
        payload["owner_name"] = row["owner_name"]
        payload["owner_email"] = row["owner_email"]
    if include_text:
        payload["transcript"] = row["transcript"] if payload["has_text"] else None
    return payload


def get_job(job_id: str, user_id: int | None = None, *, include_text: bool = False) -> dict[str, Any] | None:
    query = """
        SELECT j.*, c.name AS course_name, c.color AS course_color
        FROM jobs j LEFT JOIN courses c ON c.id = j.course_id
        WHERE j.id = ?
    """
    params: tuple[Any, ...] = (job_id,)
    if user_id is not None:
        query += " AND j.user_id = ?"
        params += (user_id,)
    with connection() as database:
        row = database.execute(query, params).fetchone()
    return serialize_job(row, include_text=include_text) if row else None


def get_job_record(job_id: str) -> sqlite3.Row | None:
    with connection() as database:
        return database.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def list_jobs(user_id: int | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(500, limit))
    if user_id is None:
        query = """
            SELECT j.*, u.name AS owner_name, u.email AS owner_email,
                   c.name AS course_name, c.color AS course_color
            FROM jobs j JOIN users u ON u.id = j.user_id
            LEFT JOIN courses c ON c.id = j.course_id
            ORDER BY j.created_at DESC LIMIT ?
        """
        params: tuple[Any, ...] = (limit,)
    else:
        query = """
            SELECT j.*, c.name AS course_name, c.color AS course_color
            FROM jobs j LEFT JOIN courses c ON c.id = j.course_id
            WHERE j.user_id = ? ORDER BY j.created_at DESC LIMIT ?
        """
        params = (user_id, limit)
    with connection() as database:
        rows = database.execute(query, params).fetchall()
    return [serialize_job(row) for row in rows]


def list_course_jobs(course_id: int, user_id: int, *, limit: int = 500) -> list[dict[str, Any]]:
    limit = max(1, min(500, limit))
    with connection() as database:
        rows = database.execute(
            """
            SELECT j.*, c.name AS course_name, c.color AS course_color
            FROM jobs j JOIN courses c ON c.id = j.course_id
            WHERE j.course_id = ? AND j.user_id = ?
            ORDER BY COALESCE(j.lesson_date, substr(j.created_at, 1, 10)) DESC,
                     j.created_at DESC
            LIMIT ?
            """,
            (course_id, user_id, limit),
        ).fetchall()
    return [serialize_job(row) for row in rows]


def user_stats(user_id: int) -> dict[str, Any]:
    with connection() as database:
        row = database.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN stored_audio_name IS NOT NULL AND audio_deleted = 0 THEN 1 ELSE 0 END) AS audios,
                   SUM(CASE WHEN transcript IS NOT NULL AND text_deleted = 0 THEN 1 ELSE 0 END) AS texts,
                   COALESCE(SUM(CASE WHEN audio_deleted = 0 THEN audio_size ELSE 0 END), 0) AS storage
            FROM jobs WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    return {key: int(row[key] or 0) for key in ("total", "completed", "audios", "texts", "storage")}


def admin_stats() -> dict[str, Any]:
    with connection() as database:
        users = database.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_users = database.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0]
        row = database.execute(
            """
            SELECT COUNT(*) AS jobs,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN status IN ('queued','loading','processing','exporting') THEN 1 ELSE 0 END) AS active_jobs,
                   COALESCE(SUM(CASE WHEN audio_deleted = 0 THEN audio_size ELSE 0 END), 0) AS storage
            FROM jobs
            """
        ).fetchone()
    return {
        "users": int(users), "active_users": int(active_users), "jobs": int(row["jobs"] or 0),
        "completed": int(row["completed"] or 0), "active_jobs": int(row["active_jobs"] or 0),
        "storage": int(row["storage"] or 0),
    }


def list_users() -> list[dict[str, Any]]:
    with connection() as database:
        rows = database.execute(
            """
            SELECT u.*, COUNT(j.id) AS job_count
            FROM users u LEFT JOIN jobs j ON j.user_id = u.id
            GROUP BY u.id ORDER BY u.created_at DESC
            """
        ).fetchall()
    return [public_user(row) | {"job_count": int(row["job_count"])} for row in rows]


def set_user_active(user_id: int, is_active: bool) -> bool:
    with connection() as database:
        cursor = database.execute(
            "UPDATE users SET is_active = ? WHERE id = ?", (int(is_active), user_id)
        )
        if not is_active:
            database.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return cursor.rowcount > 0


def promote_user(email: str) -> bool:
    with connection() as database:
        cursor = database.execute(
            "UPDATE users SET role = 'admin' WHERE email = ?", (normalize_email(email),)
        )
    return cursor.rowcount > 0


def clear_job_audio(job_id: str) -> None:
    update_job(job_id, stored_audio_name=None, audio_size=0, audio_deleted=1)


def clear_job_text(job_id: str) -> None:
    update_job(job_id, transcript=None, segments_json=None, text_deleted=1)


def delete_job(job_id: str) -> None:
    with connection() as database:
        database.execute("DELETE FROM jobs WHERE id = ?", (job_id,))


def segments_to_json(segments: list[dict[str, Any]]) -> str:
    return json.dumps(segments, ensure_ascii=False)
