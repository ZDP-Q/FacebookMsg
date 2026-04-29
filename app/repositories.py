from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any

from app.database import get_connection
from app.security import now_utc, now_utc_sql, session_expiry_sql


def list_accounts() -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, name, page_access_token, verify_token, page_id, api_version, is_active, created_at, updated_at
            FROM account_configs
            ORDER BY is_active DESC, id ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_active_account() -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, name, page_access_token, verify_token, page_id, api_version, is_active, created_at, updated_at
            FROM account_configs
            WHERE is_active = 1
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def get_account_by_id(account_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, name, page_access_token, verify_token, page_id, api_version, is_active, created_at, updated_at
            FROM account_configs
            WHERE id = ?
            """,
            (account_id,),
        ).fetchone()
    return dict(row) if row else None


def get_account_by_page_id(page_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, name, page_access_token, verify_token, page_id, api_version, is_active, created_at, updated_at
            FROM account_configs
            WHERE page_id = ?
            LIMIT 1
            """,
            (page_id,),
        ).fetchone()
    return dict(row) if row else None


def get_account_by_verify_token(verify_token: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, name, page_access_token, verify_token, page_id, api_version, is_active, created_at, updated_at
            FROM account_configs
            WHERE verify_token = ?
            LIMIT 1
            """,
            (verify_token,),
        ).fetchone()
    return dict(row) if row else None


def create_account(
    *,
    name: str,
    page_access_token: str,
    verify_token: str,
    page_id: str,
    api_version: str,
    is_active: int = 0,
) -> int:
    with get_connection() as connection:
        if is_active:
            connection.execute("UPDATE account_configs SET is_active = 0")
        cursor = connection.execute(
            """
            INSERT INTO account_configs (
                name, page_access_token, verify_token, page_id, api_version, is_active, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (name, page_access_token, verify_token, page_id, api_version, int(bool(is_active))),
        )
        return int(cursor.lastrowid)


def update_account(account_id: int, **kwargs: Any) -> None:
    allowed = {"name", "page_access_token", "verify_token", "page_id", "api_version", "is_active"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    with get_connection() as connection:
        if "is_active" in fields and int(bool(fields["is_active"])) == 1:
            connection.execute("UPDATE account_configs SET is_active = 0")
            fields["is_active"] = 1
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [account_id]
        connection.execute(
            f"UPDATE account_configs SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )


def delete_account(account_id: int) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM account_configs WHERE id = ?", (account_id,))
        active = connection.execute("SELECT id FROM account_configs WHERE is_active = 1 LIMIT 1").fetchone()
        if active is None:
            fallback = connection.execute("SELECT id FROM account_configs ORDER BY id ASC LIMIT 1").fetchone()
            if fallback is not None:
                connection.execute("UPDATE account_configs SET is_active = 1 WHERE id = ?", (fallback["id"],))


def set_active_account(account_id: int) -> None:
    with get_connection() as connection:
        connection.execute("UPDATE account_configs SET is_active = 0")
        connection.execute(
            "UPDATE account_configs SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (account_id,),
        )


def bulk_import_accounts(accounts: list[dict[str, Any]]) -> int:
    """Import multiple accounts, UPSERT by page_id."""
    count = 0
    with get_connection() as connection:
        for acc in accounts:
            page_id = str(acc.get("page_id", "")).strip()
            if not page_id:
                continue
            
            connection.execute(
                """
                INSERT INTO account_configs (name, page_access_token, verify_token, page_id, api_version, is_active, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
                ON CONFLICT(page_id) DO UPDATE SET
                    name = excluded.name,
                    page_access_token = excluded.page_access_token,
                    verify_token = excluded.verify_token,
                    api_version = excluded.api_version,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    acc.get("name", f"Imported {page_id}"),
                    acc.get("page_access_token", ""),
                    acc.get("verify_token", ""),
                    page_id,
                    acc.get("api_version", "v25.0") or "v25.0",
                ),
            )
            count += 1
        
        if count > 0:
            connection.execute("DELETE FROM account_configs WHERE name = '默认账号' OR page_id = 'default-page'")
            
    return count


def get_model_config() -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, ai_api_base_url, ai_api_key, ai_model, prompt_template, updated_at
            FROM model_configs
            WHERE id = 1
            """
        ).fetchone()
    return dict(row) if row else None


def upsert_model_config(*, ai_api_base_url: str, ai_api_key: str, ai_model: str, prompt_template: str = 'reply_prompt.j2') -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO model_configs (id, ai_api_base_url, ai_api_key, ai_model, prompt_template, updated_at)
            VALUES (1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                ai_api_base_url = excluded.ai_api_base_url,
                ai_api_key = excluded.ai_api_key,
                ai_model = excluded.ai_model,
                prompt_template = excluded.prompt_template,
                updated_at = CURRENT_TIMESTAMP
            """,
            (ai_api_base_url, ai_api_key, ai_model, prompt_template),
        )


def upsert_page_profile(profile: dict[str, Any]) -> None:
    picture_url = profile.get("picture", {}).get("data", {}).get("url", "")
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO page_profiles (page_id, name, username, link, picture_url, fan_count, category, raw_json, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(page_id) DO UPDATE SET
                name = excluded.name,
                username = excluded.username,
                link = excluded.link,
                picture_url = excluded.picture_url,
                fan_count = excluded.fan_count,
                category = excluded.category,
                raw_json = excluded.raw_json,
                synced_at = CURRENT_TIMESTAMP
            """,
            (
                profile.get("id", ""),
                profile.get("name", ""),
                profile.get("username", ""),
                profile.get("link", ""),
                picture_url,
                profile.get("fan_count", 0),
                profile.get("category", ""),
                json.dumps(profile, ensure_ascii=False),
            ),
        )


def get_page_profile(page_id: str | None = None) -> dict[str, Any] | None:
    with get_connection() as connection:
        if page_id:
            row = connection.execute(
                """
                SELECT page_id, name, username, link, picture_url, fan_count, category, synced_at
                FROM page_profiles
                WHERE page_id = ? OR username = ?
                ORDER BY synced_at DESC
                LIMIT 1
                """,
                (page_id, page_id),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT page_id, name, username, link, picture_url, fan_count, category, synced_at FROM page_profiles ORDER BY synced_at DESC LIMIT 1"
            ).fetchone()

    return dict(row) if row else None


def get_canonical_page_id(page_id: str) -> str:
    """Resolve a page_id (could be numeric or username) to its canonical numeric ID."""
    profile = get_page_profile(page_id)
    if profile:
        return profile["page_id"]
    return page_id


def upsert_post(page_id: str, post: dict[str, Any]) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO posts (id, page_id, message, created_time, full_picture, permalink_url, type, raw_json, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                page_id = excluded.page_id,
                message = excluded.message,
                created_time = excluded.created_time,
                full_picture = excluded.full_picture,
                permalink_url = excluded.permalink_url,
                type = excluded.type,
                raw_json = excluded.raw_json,
                synced_at = CURRENT_TIMESTAMP
            """,
            (
                post["id"],
                page_id,
                post.get("message", ""),
                post.get("created_time", ""),
                post.get("full_picture", ""),
                post.get("permalink_url", ""),
                post.get("type", ""),
                json.dumps(post, ensure_ascii=False),
            ),
        )


def replace_comments_for_post(post_id: str, comments: list[dict[str, Any]]) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
        for comment in comments:
            _insert_comment(connection, post_id, None, comment)


def _insert_comment(connection, post_id: str, parent_comment_id: str | None, comment: dict[str, Any]) -> None:
    author = comment.get("from", {})
    connection.execute(
        """
        INSERT INTO comments (id, post_id, parent_comment_id, message, author_name, author_id, created_time, raw_json, synced_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            comment["id"],
            post_id,
            parent_comment_id,
            comment.get("message", ""),
            author.get("name", "匿名用户"),
            author.get("id", ""),
            comment.get("created_time", ""),
            json.dumps(comment, ensure_ascii=False),
        ),
    )

    for reply in comment.get("replies", {}).get("data", []):
        _insert_comment(connection, post_id, comment["id"], reply)


def list_posts(page_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    with get_connection() as connection:
        if page_id:
            query = "SELECT id, page_id, message, created_time, full_picture, permalink_url, type, raw_json, synced_at FROM posts WHERE page_id = ? ORDER BY created_time DESC, id DESC"
            params = [page_id]
        else:
            query = "SELECT id, page_id, message, created_time, full_picture, permalink_url, type, raw_json, synced_at FROM posts ORDER BY created_time DESC, id DESC"
            params = []
            
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
            
        rows = connection.execute(query, tuple(params)).fetchall()
        
    return [dict(row) for row in rows]


def delete_posts(post_ids: list[str]) -> None:
    if not post_ids:
        return
    placeholders = ",".join("?" for _ in post_ids)
    with get_connection() as connection:
        # Cascade delete will handle comments if foreign keys are enabled
        connection.execute(
            f"DELETE FROM posts WHERE id IN ({placeholders})",
            post_ids,
        )


def clear_page_posts(page_id: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM posts WHERE page_id = ?",
            (page_id,),
        )


def get_post(post_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, page_id, message, created_time, full_picture, permalink_url, synced_at FROM posts WHERE id = ?",
            (post_id,),
        ).fetchone()
    return dict(row) if row else None


def get_comment(comment_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, post_id, parent_comment_id, message, author_name, author_id, created_time, synced_at
            FROM comments WHERE id = ?
            """,
            (comment_id,),
        ).fetchone()
    return dict(row) if row else None


def list_comments_by_post_ids(post_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not post_ids:
        return {}

    placeholders = ",".join("?" for _ in post_ids)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT id, post_id, parent_comment_id, message, author_name, author_id, created_time, synced_at
            FROM comments
            WHERE post_id IN ({placeholders})
            ORDER BY created_time ASC, id ASC
            """,
            post_ids,
        ).fetchall()

    comments_by_post: dict[str, list[dict[str, Any]]] = {post_id: [] for post_id in post_ids}
    comment_map: dict[str, dict[str, Any]] = {}

    for row in rows:
        item = dict(row)
        item["replies"] = []
        comment_map[item["id"]] = item

    for item in comment_map.values():
        parent_id = item["parent_comment_id"]
        if parent_id and parent_id in comment_map:
            comment_map[parent_id]["replies"].append(item)
        else:
            # 父评论不存在（例如抓取窗口外）时，回退到顶级展示，避免评论丢失。
            if item["post_id"] in comments_by_post:
                comments_by_post[item["post_id"]].append(item)
    
    return comments_by_post


def delete_comment_local(comment_id: str) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM comments WHERE id = ?", (comment_id,))



# ---------------------------------------------------------------------------
# Post monitors
# ---------------------------------------------------------------------------

def create_monitor(post_id: str, interval_seconds: int = 300, max_depth: int = 1) -> int:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO post_monitors (post_id, enabled, interval_seconds, max_depth)
            VALUES (?, 1, ?, ?)
            """,
            (post_id, interval_seconds, max_depth),
        )
        row = connection.execute(
            "SELECT id FROM post_monitors WHERE post_id = ?", (post_id,)
        ).fetchone()
        return row["id"]


def list_monitors(page_id: str | None = None) -> list[dict[str, Any]]:
    with get_connection() as connection:
        if page_id:
            rows = connection.execute(
                """
                SELECT m.id, m.post_id, m.enabled, m.interval_seconds, m.max_depth,
                       m.created_at, m.last_run_at, m.last_run_status,
                       p.page_id, p.message AS post_message, p.created_time AS post_created_time,
                       p.permalink_url
                FROM post_monitors m
                LEFT JOIN posts p ON m.post_id = p.id
                WHERE p.page_id = ?
                ORDER BY m.created_at DESC
                """,
                (page_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT m.id, m.post_id, m.enabled, m.interval_seconds, m.max_depth,
                       m.created_at, m.last_run_at, m.last_run_status,
                       p.page_id, p.message AS post_message, p.created_time AS post_created_time,
                       p.permalink_url
                FROM post_monitors m
                LEFT JOIN posts p ON m.post_id = p.id
                ORDER BY m.created_at DESC
                """
            ).fetchall()
    return [dict(row) for row in rows]


def get_monitor(monitor_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT m.id, m.post_id, m.enabled, m.interval_seconds, m.max_depth,
                   m.created_at, m.last_run_at, m.last_run_status,
                   p.page_id, p.message AS post_message, p.created_time AS post_created_time,
                   p.permalink_url
            FROM post_monitors m
            LEFT JOIN posts p ON m.post_id = p.id
            WHERE m.id = ?
            """,
            (monitor_id,),
        ).fetchone()
    return dict(row) if row else None


def get_monitor_by_post(post_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM post_monitors WHERE post_id = ?", (post_id,)
        ).fetchone()
    return dict(row) if row else None


def update_monitor(monitor_id: int, **kwargs: Any) -> None:
    allowed = {"enabled", "interval_seconds", "max_depth", "last_run_at", "last_run_status"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [monitor_id]
    with get_connection() as connection:
        connection.execute(
            f"UPDATE post_monitors SET {set_clause} WHERE id = ?", values
        )


def list_monitored_post_ids(page_id: str) -> set[str]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT m.post_id
            FROM post_monitors m
            LEFT JOIN posts p ON m.post_id = p.id
            WHERE p.page_id = ?
            """,
            (page_id,),
        ).fetchall()
    return {row["post_id"] for row in rows}


# ---------------------------------------------------------------------------
# Replied comments (auto-reply deduplication)
# ---------------------------------------------------------------------------

def has_replied(comment_id: str) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT 1 FROM replied_comments WHERE comment_id = ?", (comment_id,)
        ).fetchone()
    return row is not None


def mark_replied(comment_id: str, post_id: str, monitor_id: int | None, reply_message: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO replied_comments (comment_id, post_id, monitor_id, reply_message)
            VALUES (?, ?, ?, ?)
            """,
            (comment_id, post_id, monitor_id, reply_message),
        )


def unmark_replied(comment_id: str) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM replied_comments WHERE comment_id = ?", (comment_id,))


def list_replied_for_monitor(monitor_id: int, limit: int = 50) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT r.comment_id, r.post_id, r.monitor_id, r.reply_message, r.replied_at,
                   c.message AS comment_message, c.author_name
            FROM replied_comments r
            INNER JOIN comments c ON r.comment_id = c.id
            WHERE r.monitor_id = ?
            ORDER BY r.replied_at DESC
            LIMIT ?
            """,
            (monitor_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_comment(post_id: str, parent_comment_id: str | None, comment: dict[str, Any]) -> None:
    """Insert or update a single comment (used by monitor service for incremental updates)."""
    author = comment.get("from", {})
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO comments (id, post_id, parent_comment_id, message, author_name, author_id, created_time, raw_json, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                message = excluded.message,
                author_name = excluded.author_name,
                author_id = excluded.author_id,
                raw_json = excluded.raw_json,
                synced_at = CURRENT_TIMESTAMP
            """,
            (
                comment["id"],
                post_id,
                parent_comment_id,
                comment.get("message", ""),
                author.get("name", "匿名用户"),
                author.get("id", ""),
                comment.get("created_time", ""),
                json.dumps(comment, ensure_ascii=False),
            ),
        )
    for reply in comment.get("replies", {}).get("data", []):
        upsert_comment(post_id, comment["id"], reply)


# ---------------------------------------------------------------------------
# Admin auth
# ---------------------------------------------------------------------------

def get_admin_auth() -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, username, password_hash, password_salt, password_iterations, force_password_change, updated_at
            FROM admin_auth
            WHERE id = 1
            """
        ).fetchone()
    return dict(row) if row else None


def update_admin_password(*, password_hash: str, password_salt: str, password_iterations: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE admin_auth
            SET password_hash = ?,
                password_salt = ?,
                password_iterations = ?,
                force_password_change = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (password_hash, password_salt, password_iterations),
        )


def create_admin_session(*, session_id: str, ip: str, user_agent: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO admin_sessions (session_id, expires_at, ip, user_agent)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, session_expiry_sql(), ip[:120], user_agent[:512]),
        )


def get_admin_session(session_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT session_id, expires_at, created_at, last_seen_at, ip, user_agent
            FROM admin_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()

    if not row:
        return None

    session = dict(row)
    expires_at = str(session.get("expires_at", ""))
    if not expires_at:
        return None
    if now_utc_sql() >= expires_at:
        delete_admin_session(session_id)
        return None
    return session


def touch_admin_session(session_id: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE admin_sessions
            SET expires_at = ?,
                last_seen_at = CURRENT_TIMESTAMP
            WHERE session_id = ?
            """,
            (session_expiry_sql(), session_id),
        )


def delete_admin_session(session_id: str) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM admin_sessions WHERE session_id = ?", (session_id,))


def delete_all_admin_sessions() -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM admin_sessions")


def cleanup_expired_admin_sessions() -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (now_utc_sql(),))


def is_ip_locked(ip: str) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT lock_until FROM admin_login_attempts WHERE ip = ?",
            (ip,),
        ).fetchone()
    if not row:
        return False
    lock_until = str(row["lock_until"] or "")
    return bool(lock_until and now_utc_sql() < lock_until)


def register_failed_login(ip: str) -> int:
    now = now_utc()
    now_sql = now_utc_sql()
    lock_window_minutes = 15
    max_attempts = 5

    with get_connection() as connection:
        row = connection.execute(
            "SELECT failed_count, first_failed_at, lock_until FROM admin_login_attempts WHERE ip = ?",
            (ip,),
        ).fetchone()

        if row:
            lock_until = str(row["lock_until"] or "")
            if lock_until and now_sql < lock_until:
                return int(row["failed_count"] or max_attempts)

            first_failed_at = str(row["first_failed_at"] or "")
            failed_count = int(row["failed_count"] or 0)

            if not first_failed_at:
                failed_count = 1
                first_failed_at = now_sql
            else:
                try:
                    first_failed_dt = datetime.strptime(first_failed_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                    age_min = (now - first_failed_dt).total_seconds() / 60
                except Exception:
                    age_min = lock_window_minutes + 1

                if age_min > lock_window_minutes:
                    failed_count = 1
                    first_failed_at = now_sql
                else:
                    failed_count += 1

            new_lock_until = ""
            if failed_count >= max_attempts:
                new_lock_until = (now + timedelta(minutes=lock_window_minutes)).strftime("%Y-%m-%d %H:%M:%S")

            connection.execute(
                """
                UPDATE admin_login_attempts
                SET failed_count = ?,
                    first_failed_at = ?,
                    lock_until = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE ip = ?
                """,
                (failed_count, first_failed_at, new_lock_until or None, ip),
            )
            return failed_count

        connection.execute(
            """
            INSERT INTO admin_login_attempts (ip, failed_count, first_failed_at, lock_until, updated_at)
            VALUES (?, 1, ?, NULL, CURRENT_TIMESTAMP)
            """,
            (ip, now_sql),
        )
        return 1



def clear_login_attempts(ip: str) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM admin_login_attempts WHERE ip = ?", (ip,))
