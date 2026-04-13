"""
database.py
SQLite persistence layer for the IVF Lead Engine.

Table: leads
  id            – autoincrement primary key
  session_id    – unique per conversation
  phone         – caller's phone (WhatsApp) or None (API)
  lead_score    – Hot / Warm / Cold
  status        – active | in_progress | awaiting_confirmation |
                  dropped_s2 | dropped_s5 | declined | complete
  state_reached – last state seen (S1–S6)
  source        – "whatsapp" | "api"
  collected_data– JSON blob (duration, age, treatment, phone_number)
  created_at    – ISO-8601 UTC
  updated_at    – ISO-8601 UTC
"""

import json
import sqlite3
from datetime import datetime
from typing import Optional

DB_PATH = "leads.db"


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """
    Create the leads table if it doesn't exist. Safe to call on every startup.
    v2.0 — adds counselor_brief, priority_rank, call_outcome, follow_up_at columns.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")   # better concurrency for reads
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT    UNIQUE NOT NULL,
            phone           TEXT,
            lead_score      TEXT,
            status          TEXT    DEFAULT 'active',
            state_reached   TEXT,
            source          TEXT    DEFAULT 'api',
            collected_data  TEXT,
            counselor_brief TEXT,                    -- JSON: Lead Intelligence Report
            priority_rank   INTEGER DEFAULT 5,       -- 1 (urgent) to 5 (low)
            call_outcome    TEXT,                    -- booked/follow_up/not_interested/etc.
            follow_up_at    TEXT,                    -- ISO-8601 UTC
            call_notes      TEXT,
            created_at      TEXT    NOT NULL,
            updated_at      TEXT    NOT NULL
        )
    """)
    # Safe migration for existing databases (adds columns if missing)
    _migrate(conn)
    conn.commit()
    conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add new columns to existing leads table without breaking old data."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
    new_cols = [
        ("counselor_brief", "TEXT"),
        ("priority_rank",   "INTEGER DEFAULT 5"),
        ("call_outcome",    "TEXT"),
        ("follow_up_at",    "TEXT"),
        ("call_notes",      "TEXT"),
        ("state_reached",   "TEXT"),
        ("collected_data",  "TEXT"),
        # Phase 3: Booking columns
        ("booking_date",    "TEXT"),           # YYYY-MM-DD
        ("booking_time",    "TEXT"),           # HH:MM (e.g. "11:00", "15:00")
        ("booking_status",  "TEXT"),           # pending / confirmed / cancelled / completed
        ("lead_priority",   "TEXT"),           # high / medium / low
        ("intent_level",    "TEXT"),           # confirmed / exploring / vague
    ]
    for col, definition in new_cols:
        if col not in existing:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {definition}")


# ── Write ─────────────────────────────────────────────────────────────────────

def upsert_lead(
    session_id: str,
    phone: Optional[str] = None,
    lead_score: Optional[str] = None,
    status: str = "active",
    state_reached: Optional[str] = None,
    source: str = "api",
    collected_data: Optional[dict] = None,
    counselor_brief: Optional[dict] = None,
    priority_rank: Optional[int] = None,
) -> None:
    """
    Insert a new lead row, or update if session_id already exists.
    Caller does not need to check existence first.
    """
    now          = datetime.utcnow().isoformat() + "Z"
    data_json    = json.dumps(collected_data or {}, ensure_ascii=False)
    brief_json   = json.dumps(counselor_brief, ensure_ascii=False) if counselor_brief else None

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        existing = conn.execute(
            "SELECT id FROM leads WHERE session_id = ?", (session_id,)
        ).fetchone()

        if existing:
            # Build dynamic SET clause — only update counselor_brief / priority_rank
            # if they are explicitly provided (don't overwrite with None)
            set_clauses = [
                "phone = ?", "lead_score = ?", "status = ?",
                "state_reached = ?", "source = ?", "collected_data = ?",
                "updated_at = ?",
            ]
            values = [phone, lead_score, status, state_reached,
                      source, data_json, now]

            if brief_json is not None:
                set_clauses.append("counselor_brief = ?")
                values.append(brief_json)
            if priority_rank is not None:
                set_clauses.append("priority_rank = ?")
                values.append(priority_rank)

            values.append(session_id)
            conn.execute(
                f"UPDATE leads SET {', '.join(set_clauses)} WHERE session_id = ?",
                values,
            )
        else:
            conn.execute(
                """
                INSERT INTO leads
                    (session_id, phone, lead_score, status, state_reached,
                     source, collected_data, counselor_brief, priority_rank,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, phone, lead_score, status, state_reached,
                 source, data_json, brief_json, priority_rank or 5, now, now),
            )

        conn.commit()
    finally:
        conn.close()


# ── Read ──────────────────────────────────────────────────────────────────────

def get_all_leads(
    status: Optional[str] = None,
    date: Optional[str] = None,         # expected format: YYYY-MM-DD
) -> list:
    """
    Return all leads as a list of dicts.
    Optional filters: status (exact match) and date (created_at date).
    """
    query  = "SELECT * FROM leads WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if date:
        query += " AND DATE(created_at) = ?"
        params.append(date)

    query += " ORDER BY created_at DESC"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # allows dict-like access
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    leads = []
    for row in rows:
        d = dict(row)
        try:
            d["collected_data"] = json.loads(d.get("collected_data") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["collected_data"] = {}
        try:
            d["counselor_brief"] = json.loads(d.get("counselor_brief") or "null")
        except (json.JSONDecodeError, TypeError):
            d["counselor_brief"] = None
        leads.append(d)

    return leads


def has_completed_lead(phone: str) -> bool:
    """
    Check if a completed/transferred lead already exists for this phone number.
    Used to prevent restarting intake when user sends post-completion messages.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT id FROM leads WHERE phone = ? AND status IN ('transferred', 'completed', 'call_scheduled') ORDER BY created_at DESC LIMIT 1",
            (phone,)
        ).fetchone()
    finally:
        conn.close()
    return row is not None
