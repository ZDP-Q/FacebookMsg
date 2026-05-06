from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT
from app.security import PBKDF2_ITERATIONS, generate_salt, hash_password, is_strong_password

DB_PATH = PROJECT_ROOT / "data" / "facebookmsg.sqlite3"
POSTS_JSON = PROJECT_ROOT / "posts_db.json"
COMMENTS_JSON = PROJECT_ROOT / "comments_db.json"

logger = logging.getLogger("uvicorn.error")

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS page_profiles (
    page_id TEXT PRIMARY KEY,
    name TEXT,
    username TEXT,
    link TEXT,
    picture_url TEXT,
    fan_count INTEGER,
    category TEXT,
    raw_json TEXT NOT NULL,
    synced_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL,
    message TEXT,
    created_time TEXT,
    full_picture TEXT,
    permalink_url TEXT,
    type TEXT NOT NULL DEFAULT '',
    is_hidden INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT NOT NULL,
    synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (page_id) REFERENCES page_profiles(page_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    parent_comment_id TEXT,
    message TEXT,
    author_name TEXT,
    author_id TEXT,
    created_time TEXT,
    raw_json TEXT NOT NULL,
    synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_comment_id) REFERENCES comments(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_posts_page_id ON posts(page_id);
CREATE INDEX IF NOT EXISTS idx_comments_post_id ON comments(post_id);
CREATE INDEX IF NOT EXISTS idx_comments_parent_id ON comments(parent_comment_id);

CREATE TABLE IF NOT EXISTS post_monitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    interval_seconds INTEGER NOT NULL DEFAULT 300,
    max_depth INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_run_at TEXT,
    last_run_status TEXT,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS replied_comments (
    comment_id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    monitor_id INTEGER,
    reply_message TEXT,
    replied_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_replied_post ON replied_comments(post_id);
CREATE INDEX IF NOT EXISTS idx_replied_monitor ON replied_comments(monitor_id);

CREATE TABLE IF NOT EXISTS account_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',
    page_access_token TEXT NOT NULL,
    verify_token TEXT NOT NULL,
    page_id TEXT NOT NULL UNIQUE,
    api_version TEXT NOT NULL DEFAULT 'v25.0',
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_account_active ON account_configs(is_active);

CREATE TABLE IF NOT EXISTS model_configs (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    ai_api_base_url TEXT NOT NULL DEFAULT '',
    ai_api_key TEXT NOT NULL DEFAULT '',
    ai_model TEXT NOT NULL DEFAULT '',
    prompt_template TEXT NOT NULL DEFAULT 'reply_prompt.j2',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_auth (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    password_iterations INTEGER NOT NULL DEFAULT 390000,
    force_password_change INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    session_id TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
    ip TEXT,
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires_at ON admin_sessions(expires_at);

CREATE TABLE IF NOT EXISTS admin_login_attempts (
    ip TEXT PRIMARY KEY,
    failed_count INTEGER NOT NULL DEFAULT 0,
    first_failed_at TEXT,
    lock_until TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admin_login_lock_until ON admin_login_attempts(lock_until);
"""


from contextlib import contextmanager

@contextmanager
def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(SCHEMA_SQL)

    # Migration: add columns if they don't exist yet
    with get_connection() as connection:
        try:
            connection.execute("ALTER TABLE posts ADD COLUMN type TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        
        try:
            connection.execute("ALTER TABLE posts ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        
        try:
            connection.execute("ALTER TABLE model_configs ADD COLUMN prompt_template TEXT NOT NULL DEFAULT 'reply_prompt.j2'")
        except Exception:
            pass

    _seed_settings_from_legacy_json_if_needed()
    _seed_admin_auth_if_needed()


def _seed_settings_from_legacy_json_if_needed() -> None:
    """Seed settings tables from legacy config.json on first startup.

    Runtime config is now DB-driven; legacy JSON is used only as bootstrap data.
    """
    with get_connection() as connection:
        count = connection.execute("SELECT COUNT(*) FROM account_configs").fetchone()[0]
        if count:
            return

    raw = _load_json(PROJECT_ROOT / "config.json", {})

    page_id = str(raw.get("PAGE_ID", "")).strip()
    if not page_id:
        page_id = "default-page"

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO account_configs (
                name, page_access_token, verify_token, page_id, api_version, is_active, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            """,
            (
                "默认账号",
                str(raw.get("PAGE_ACCESS_TOKEN", "")),
                str(raw.get("VERIFY_TOKEN", "")),
                page_id,
                str(raw.get("API_VERSION", "v25.0")) or "v25.0",
            ),
        )

        connection.execute(
            """
            INSERT INTO model_configs (
                id, ai_api_base_url, ai_api_key, ai_model, updated_at
            )
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                ai_api_base_url = excluded.ai_api_base_url,
                ai_api_key = excluded.ai_api_key,
                ai_model = excluded.ai_model,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                1,
                str(raw.get("AI_API_BASE_URL", "")),
                str(raw.get("AI_API_KEY", "")),
                str(raw.get("AI_MODEL", "")),
            ),
        )


def _seed_admin_auth_if_needed() -> None:
    with get_connection() as connection:
        row = connection.execute("SELECT id FROM admin_auth WHERE id = 1").fetchone()
        if row:
            return

        username = "admin"
        env_password = str(os.getenv("ADMIN_PASSWORD", "")).strip()

        if not env_password or not is_strong_password(env_password):
            raise RuntimeError("首次启动请设置强密码环境变量 ADMIN_PASSWORD（至少16位，包含大小写字母、数字和符号）")

        password = env_password
        force_change = 0
        logger.info("[auth] admin account initialized from ADMIN_PASSWORD")

        salt = generate_salt()
        password_hash = hash_password(password, salt, PBKDF2_ITERATIONS)

        connection.execute(
            """
            INSERT INTO admin_auth (
                id, username, password_hash, password_salt, password_iterations, force_password_change, updated_at
            )
            VALUES (1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (username, password_hash, salt, PBKDF2_ITERATIONS, force_change),
        )

def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError:
            return default


def migrate_legacy_json_if_needed() -> bool:
    from app.repositories import upsert_post, upsert_page_profile, replace_comments_for_post

    with get_connection() as connection:
        post_count = connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        comment_count = connection.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        profile_count = connection.execute("SELECT COUNT(*) FROM page_profiles").fetchone()[0]

    if post_count or comment_count or profile_count:
        return False

    posts = _load_json(POSTS_JSON, [])
    comments_by_post = _load_json(COMMENTS_JSON, {})
    if not posts and not comments_by_post:
        return False

    page_id = posts[0].get("id", "").split("_")[0] if posts else "legacy-page"
    upsert_page_profile(
        {
            "id": page_id,
            "name": "Legacy Imported Page",
            "username": "",
            "link": "",
            "category": "",
            "fan_count": 0,
            "picture": {"data": {"url": ""}},
        }
    )

    for post in posts:
        upsert_post(page_id, post)
        replace_comments_for_post(post["id"], comments_by_post.get(post["id"], []))

    return True
