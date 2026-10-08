"""Neon Postgres and Data API-backed chat history."""

from __future__ import annotations

from datetime import datetime
from typing import Any
import sqlite3
import uuid

import requests

from core.paths import CHAT_DB_FILE
from memory.config_manager import load_api_keys

TABLE_NAME = "chat_messages"
REQUEST_TIMEOUT = 15

_schema_initialized = False


class ChatHistoryError(RuntimeError):
    """Raised when chat history cannot be read or written."""


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    res = dict(row)
    if "id" in res and res["id"] is not None:
        res["id"] = str(res["id"])
    if "sent_at" in res and res["sent_at"] is not None:
        if hasattr(res["sent_at"], "isoformat"):
            res["sent_at"] = res["sent_at"].isoformat()
        else:
            res["sent_at"] = str(res["sent_at"])
    return res


def _get_pg_connection(database_url: str):
    try:
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            database_url,
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=REQUEST_TIMEOUT,
        )
    except ImportError:
        try:
            import psycopg2
            import psycopg2.extras

            conn = psycopg2.connect(database_url, connect_timeout=REQUEST_TIMEOUT)
            conn.autocommit = True
            conn.cursor_factory = psycopg2.extras.RealDictCursor
            return conn
        except ImportError as exc:
            raise ChatHistoryError(
                "PostgreSQL driver not found. Install psycopg with: pip install 'psycopg[binary]'"
            ) from exc


def _ensure_schema(conn) -> None:
    global _schema_initialized
    if _schema_initialized:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.chat_messages (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                conversation_id text NOT NULL,
                sender_id text NOT NULL,
                sender_name text NOT NULL,
                message_content text NOT NULL CHECK (char_length(trim(message_content)) > 0),
                sent_at timestamptz NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS chat_messages_sent_at_idx
                ON public.chat_messages (sent_at DESC);
            CREATE INDEX IF NOT EXISTS chat_messages_conversation_id_idx
                ON public.chat_messages (conversation_id, sent_at);
            """
        )
    _schema_initialized = True


def _insert_db(database_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        with _get_pg_connection(database_url) as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.chat_messages (
                        conversation_id, sender_id, sender_name, message_content, sent_at
                    )
                    VALUES (%s, %s, %s, %s, COALESCE(%s, now()))
                    RETURNING id, conversation_id, sender_id, sender_name, message_content, sent_at;
                    """,
                    (
                        payload["conversation_id"],
                        payload["sender_id"],
                        payload["sender_name"],
                        payload["message_content"],
                        payload.get("sent_at"),
                    ),
                )
                row = cur.fetchone()
                if not row:
                    raise ChatHistoryError("Neon did not return the saved chat message.")
                return _normalize_row(dict(row))
    except Exception as exc:
        if isinstance(exc, ChatHistoryError):
            raise
        # Enhanced error logging
        import sys
        error_type = type(exc).__name__
        error_msg = str(exc)
        
        # Extract SQLSTATE if available (PostgreSQL error codes)
        sqlstate = getattr(exc, 'pgcode', None) or getattr(exc, 'sqlstate', None)
        
        detailed_msg = f"Neon database error: {error_type}: {error_msg}"
        if sqlstate:
            detailed_msg += f" (SQLSTATE: {sqlstate})"
        
        print(f"[history] insert failed: {detailed_msg}", file=sys.stderr)
        raise ChatHistoryError(detailed_msg) from exc


def _fetch_db(database_url: str, limit: int) -> list[dict[str, Any]]:
    try:
        with _get_pg_connection(database_url) as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, conversation_id, sender_id, sender_name, message_content, sent_at
                    FROM public.chat_messages
                    ORDER BY sent_at DESC
                    LIMIT %s;
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
                normalized = [_normalize_row(dict(r)) for r in rows]
                return list(reversed(normalized))
    except Exception as exc:
        if isinstance(exc, ChatHistoryError):
            raise
        raise ChatHistoryError(f"Neon database error: {exc}") from exc


def _endpoint_and_headers() -> tuple[str, dict[str, str]]:
    config = load_api_keys()
    url = str(config.get("neon_api_url", "")).strip().rstrip("/")
    jwt = str(config.get("neon_jwt", "")).strip()
    if not url:
        raise ChatHistoryError(
            "Neon is not configured. Add database_url or neon_api_url to config/api_keys.json."
        )
    if not jwt:
        raise ChatHistoryError(
            "Neon Data API requires neon_jwt in config/api_keys.json. "
            "Alternatively, provide database_url from the 'Postgres database' tab in Neon Console."
        )
    endpoint = url if url.endswith("/rest/v1") else f"{url}/rest/v1"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": "return=representation",
        "Authorization": f"Bearer {jwt}",
    }
    return endpoint, headers


def is_neon_configured() -> bool:
    """Return whether Neon is configured (via database_url or Data API with JWT)."""
    config = load_api_keys()
    db_url = str(config.get("database_url", "")).strip()
    if db_url:
        return True
    api_url = str(config.get("neon_api_url", "")).strip()
    jwt = str(config.get("neon_jwt", "")).strip()
    return bool(api_url and jwt and len(jwt) > 20 and "." in jwt)

def is_configured() -> bool:
    """Return True if *any* storage backend is available (Neon or SQLite fallback).

    This always returns True because SQLite is always available as a fallback.
    Use is_neon_configured() to test specifically whether Neon is set up.
    """
    return True


def get_neon_status() -> str:
    """Return a short status string for the UI pill: 'NEON ONLINE', 'LOCAL FALLBACK', etc."""
    if is_neon_configured():
        return "NEON ONLINE"
    return "LOCAL FALLBACK"

_sqlite_initialized = False

def _get_sqlite_connection():
    conn = sqlite3.connect(str(CHAT_DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn

def _ensure_sqlite_schema(conn) -> None:
    global _sqlite_initialized
    if _sqlite_initialized:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            sender_name TEXT NOT NULL,
            message_content TEXT NOT NULL,
            sent_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    _sqlite_initialized = True

def _insert_sqlite(payload: dict[str, Any]) -> dict[str, Any]:
    with _get_sqlite_connection() as conn:
        _ensure_sqlite_schema(conn)
        new_id = str(uuid.uuid4())
        sent_at = payload.get("sent_at")
        if not sent_at:
            from datetime import timezone
            sent_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO chat_messages (
                id, conversation_id, sender_id, sender_name, message_content, sent_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                new_id,
                payload["conversation_id"],
                payload["sender_id"],
                payload["sender_name"],
                payload["message_content"],
                sent_at
            )
        )
        conn.commit()
        return {
            "id": new_id,
            "conversation_id": payload["conversation_id"],
            "sender_id": payload["sender_id"],
            "sender_name": payload["sender_name"],
            "message_content": payload["message_content"],
            "sent_at": sent_at
        }

def _fetch_sqlite(limit: int) -> list[dict[str, Any]]:
    with _get_sqlite_connection() as conn:
        _ensure_sqlite_schema(conn)
        cursor = conn.execute(
            """
            SELECT id, conversation_id, sender_id, sender_name, message_content, sent_at
            FROM chat_messages
            ORDER BY sent_at DESC
            LIMIT ?
            """,
            (limit,)
        )
        rows = [dict(row) for row in cursor.fetchall()]
        return list(reversed(rows))


def _request(method: str, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    endpoint, headers = _endpoint_and_headers()
    try:
        response = requests.request(
            method,
            f"{endpoint}/{TABLE_NAME}",
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        detail = str(exc)
        if exc.response is not None:
            detail = f"{detail} ({exc.response.text[:200]})"
        raise ChatHistoryError(f"Neon Data API request failed: {detail}") from exc
    except ValueError as exc:
        raise ChatHistoryError(f"Neon Data API returned invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ChatHistoryError("Neon Data API returned an unexpected response shape.")
    return [_normalize_row(dict(row)) for row in data]


def insert_message(
    content: str,
    *,
    sender_id: str,
    sender_name: str,
    conversation_id: str,
    sent_at: datetime | None = None,
) -> dict[str, Any]:
    """Insert one message and return the saved row with retry mechanism."""
    message = str(content).strip()
    if not message:
        raise ValueError("Chat message content cannot be empty.")

    config = load_api_keys()
    database_url = str(config.get("database_url", "")).strip()

    payload = {
        "conversation_id": conversation_id,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "message_content": message,
    }
    if sent_at is not None:
        payload["sent_at"] = sent_at.isoformat()

    if is_neon_configured():
        # Retry mechanism for transient failures
        import time
        max_attempts = 3
        
        for attempt in range(1, max_attempts + 1):
            try:
                if database_url:
                    result = _insert_db(database_url, payload)
                    if attempt > 1:
                        print(f"[history] Neon insert succeeded on attempt {attempt}")
                    return result
                else:
                    rows = _request("POST", payload)
                    if not rows:
                        raise ChatHistoryError("Neon did not return the saved chat message.")
                    if attempt > 1:
                        print(f"[history] Neon Data API succeeded on attempt {attempt}")
                    return rows[0]
            except ChatHistoryError as e:
                is_last_attempt = (attempt == max_attempts)
                
                if is_last_attempt:
                    print(f"[history] Neon insert failed after {max_attempts} attempts: {e}. Falling back to SQLite.")
                    break
                else:
                    # Transient errors worth retrying: connection, timeout, temporary unavailability
                    error_str = str(e).lower()
                    is_transient = any(keyword in error_str for keyword in [
                        'timeout', 'connection', 'temporary', 'unavailable', 
                        'network', 'refused', 'reset'
                    ])
                    
                    if is_transient:
                        wait_time = 0.5 * attempt  # Exponential backoff: 0.5s, 1.0s
                        print(f"[history] Transient error on attempt {attempt}/{max_attempts}, retrying in {wait_time}s: {e}")
                        time.sleep(wait_time)
                    else:
                        # Non-transient error (schema, permissions, etc.) - don't retry
                        print(f"[history] Non-transient Neon error: {e}. Falling back to SQLite.")
                        break

    return _insert_sqlite(payload)


def fetch_history(limit: int = 100) -> list[dict[str, Any]]:
    """Fetch the newest messages, returned in chronological order."""
    if limit < 1:
        raise ValueError("History limit must be greater than zero.")

    config = load_api_keys()
    database_url = str(config.get("database_url", "")).strip()
    if is_neon_configured():
        if database_url:
            try:
                return _fetch_db(database_url, limit)
            except ChatHistoryError as e:
                print(f"Neon fetch failed: {e}. Falling back to SQLite.")
        else:
            endpoint, headers = _endpoint_and_headers()
            try:
                response = requests.get(
                    f"{endpoint}/{TABLE_NAME}",
                    headers=headers,
                    params={
                        "select": "id,conversation_id,sender_id,sender_name,message_content,sent_at",
                        "order": "sent_at.desc",
                        "limit": str(limit),
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                rows = response.json()
                if not isinstance(rows, list):
                    raise ChatHistoryError("Neon Data API returned an unexpected history shape.")
                return [_normalize_row(dict(row)) for row in reversed(rows)]
            except requests.RequestException as exc:
                detail = str(exc)
                if exc.response is not None:
                    detail = f"{detail} ({exc.response.text[:200]})"
                print(f"Neon Data API request failed: {detail}. Falling back to SQLite.")
            except ValueError as exc:
                print(f"Neon Data API returned invalid JSON: {exc}. Falling back to SQLite.")

    return _fetch_sqlite(limit)
