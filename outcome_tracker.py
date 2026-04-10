"""
outcome_tracker.py
Call & Lead Outcome Tracking — v1.0

Provides:
  - Outcome constants (the valid tags)
  - record_outcome() — updates a lead's outcome in the DB
  - get_conversion_metrics() — computes dashboard KPIs

Outcome tags (mandatory after every AI or counselor call):
  booked          – appointment scheduled
  follow_up       – needs another call
  not_interested  – explicitly declined
  invalid         – wrong number / not a real lead
  no_answer       – call not picked up
  consultation_done – consultation completed (post-booking)
"""

import sqlite3
import json
from datetime import datetime
from typing import Optional

DB_PATH = "leads.db"

# ── Valid outcome tags ────────────────────────────────────────────────────────
OUTCOME_BOOKED           = "booked"
OUTCOME_FOLLOW_UP        = "follow_up"
OUTCOME_NOT_INTERESTED   = "not_interested"
OUTCOME_INVALID          = "invalid"
OUTCOME_NO_ANSWER        = "no_answer"
OUTCOME_CONSULTATION_DONE = "consultation_done"

VALID_OUTCOMES = {
    OUTCOME_BOOKED, OUTCOME_FOLLOW_UP, OUTCOME_NOT_INTERESTED,
    OUTCOME_INVALID, OUTCOME_NO_ANSWER, OUTCOME_CONSULTATION_DONE,
}


# ─────────────────────────────────────────────────────────────────────────────
# DB migration — add outcome columns if they don't exist
# ─────────────────────────────────────────────────────────────────────────────

def migrate_outcome_columns() -> None:
    """
    Safe migration: adds call_outcome, counselor_brief, priority_rank columns.
    Called on startup — idempotent.
    """
    conn = sqlite3.connect(DB_PATH)
    existing_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(leads)").fetchall()
    }

    migrations = [
        ("call_outcome",    "TEXT"),
        ("counselor_brief", "TEXT"),   # JSON blob
        ("priority_rank",   "INTEGER DEFAULT 5"),
        ("follow_up_at",    "TEXT"),   # ISO-8601 UTC
        ("call_notes",      "TEXT"),
    ]

    for col_name, col_def in migrations:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {col_name} {col_def}")

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Outcome recording
# ─────────────────────────────────────────────────────────────────────────────

def record_outcome(
    session_id: str,
    outcome: str,
    call_notes: Optional[str] = None,
) -> bool:
    """
    Tag a lead with a call outcome.
    Returns True on success, False if session_id not found or outcome invalid.
    """
    if outcome not in VALID_OUTCOMES:
        return False

    now = datetime.utcnow().isoformat() + "Z"
    conn = sqlite3.connect(DB_PATH)
    try:
        result = conn.execute(
            """
            UPDATE leads
               SET call_outcome = ?,
                   call_notes   = ?,
                   updated_at   = ?
             WHERE session_id   = ?
            """,
            (outcome, call_notes, now, session_id),
        )
        conn.commit()
        return result.rowcount > 0
    finally:
        conn.close()


def store_counselor_brief(session_id: str, brief: dict, priority_rank: int = 5) -> None:
    """
    Persist the Lead Intelligence Report (counselor brief) for a session.
    """
    now = datetime.utcnow().isoformat() + "Z"
    brief_json = json.dumps(brief, ensure_ascii=False)

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            UPDATE leads
               SET counselor_brief = ?,
                   priority_rank   = ?,
                   updated_at      = ?
             WHERE session_id      = ?
            """,
            (brief_json, priority_rank, now, session_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_follow_up_time(session_id: str, follow_up_hours: int) -> None:
    """
    Store when this lead should next be followed up.
    follow_up_hours: hours from now.
    """
    from datetime import timedelta
    follow_up_at = (datetime.utcnow() + timedelta(hours=follow_up_hours)).isoformat() + "Z"
    now = datetime.utcnow().isoformat() + "Z"

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "UPDATE leads SET follow_up_at = ?, updated_at = ? WHERE session_id = ?",
            (follow_up_at, now, session_id),
        )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard conversion metrics
# ─────────────────────────────────────────────────────────────────────────────

def get_conversion_metrics(date: Optional[str] = None) -> dict:
    """
    Returns clinic conversion KPIs.
    Optional date filter: "YYYY-MM-DD"

    Metrics:
      total_leads
      hot / warm / cold counts
      contacted_pct      – % of leads with any call outcome recorded
      booked_pct         – % of total leads that booked
      not_interested_pct
      avg_priority_rank
      leads_due_follow_up – leads whose follow_up_at is in the past and not booked/done
    """
    query_base = "SELECT * FROM leads WHERE 1=1"
    params = []
    if date:
        query_base += " AND DATE(created_at) = ?"
        params.append(date)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(query_base, params).fetchall()]
    finally:
        conn.close()

    total = len(rows)
    if total == 0:
        return {"total_leads": 0, "message": "No leads found for the given filter."}

    hot   = sum(1 for r in rows if r.get("lead_score") == "Hot")
    warm  = sum(1 for r in rows if r.get("lead_score") == "Warm")
    cold  = sum(1 for r in rows if r.get("lead_score") == "Cold")

    contacted = sum(1 for r in rows if r.get("call_outcome") is not None)
    booked    = sum(1 for r in rows if r.get("call_outcome") == OUTCOME_BOOKED)
    not_int   = sum(1 for r in rows if r.get("call_outcome") == OUTCOME_NOT_INTERESTED)

    ranks = [r.get("priority_rank") or 5 for r in rows]
    avg_rank = round(sum(ranks) / len(ranks), 1)

    now_iso = datetime.utcnow().isoformat() + "Z"
    due_follow_up = sum(
        1 for r in rows
        if r.get("follow_up_at") and r["follow_up_at"] <= now_iso
        and r.get("call_outcome") not in (OUTCOME_BOOKED, OUTCOME_CONSULTATION_DONE, OUTCOME_NOT_INTERESTED)
    )

    def pct(n):
        return round(n / total * 100, 1) if total else 0

    return {
        "total_leads":          total,
        "hot_leads":            hot,
        "warm_leads":           warm,
        "cold_leads":           cold,
        "contacted_pct":        pct(contacted),
        "booked_pct":           pct(booked),
        "not_interested_pct":   pct(not_int),
        "avg_priority_rank":    avg_rank,
        "leads_due_follow_up":  due_follow_up,
        "date_filter":          date,
    }
