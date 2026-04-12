"""
sessions.py
File-based session persistence for the IVF Conversation Engine.

Serialises all engine instance state to sessions.json so in-flight
conversations survive a server restart.

What is persisted per session:
  • session_id       – string identifier
  • state            – ConversationState fields (via dataclasses.asdict)
  • consent_pending  – bool
  • collect_name     – bool
  • collect_phone    – bool
  • lead_data        – dict (name, phone captured so far)
  • s2_attempts      – int
  • s5_attempts      – int

What is NOT persisted:
  • client           – recreated per request from env var

Design:
  • One JSON file: sessions.json (sits next to app.py)
  • Thread-safe: a single threading.Lock guards every read+write pair
  • Atomic writes: write to .tmp then os.replace() → no corrupt file on crash
"""

import json
import os
import threading
from dataclasses import asdict, fields
from typing import Optional

from state_machine import ConversationState

SESSIONS_FILE = "sessions.json"
_lock = threading.Lock()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_raw() -> dict:
    """Read all sessions from file. Returns {} on any read/parse error."""
    if not os.path.exists(SESSIONS_FILE):
        return {}
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_raw(data: dict) -> None:
    """Write all sessions atomically via temp-file swap."""
    tmp = SESSIONS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SESSIONS_FILE)   # atomic on POSIX; best-effort on Windows
    except OSError:
        pass   # non-fatal — worst case: state resets on next request


def _serialize_engine(engine) -> dict:
    """Convert engine instance variables to a JSON-serialisable dict."""
    return {
        "session_id":      engine.session_id,
        "state":           asdict(engine.state),
        "consent_pending": engine.consent_pending,
        "collect_name":    engine.collect_name,
        "collect_phone":   engine.collect_phone,
        "lead_data":       engine.lead_data,
        "s2_attempts":     engine.s2_attempts,
        "s5_attempts":     engine.s5_attempts,
    }


def _restore_engine(engine, data: dict) -> None:
    """Apply saved dict back onto an existing engine instance."""
    engine.consent_pending = data.get("consent_pending", True)
    engine.collect_name    = data.get("collect_name",    False)
    engine.collect_phone   = data.get("collect_phone",   False)
    engine.lead_data       = data.get("lead_data",       {})
    engine.s2_attempts     = data.get("s2_attempts",     0)
    engine.s5_attempts     = data.get("s5_attempts",     0)

    state_data = data.get("state")
    if state_data:
        # Only restore known fields so old saved sessions don't crash on schema change
        known = {f.name for f in fields(ConversationState)}
        clean = {k: v for k, v in state_data.items() if k in known}
        try:
            engine.state = ConversationState(**clean)
        except (TypeError, AttributeError):
            pass   # keep default state if restore fails


# ── Public API ────────────────────────────────────────────────────────────────

def load_engine_state(session_id: str, engine) -> bool:
    """
    Load saved state into an already-instantiated engine.
    Returns True if a saved session was found and applied; False otherwise.
    """
    with _lock:
        data = _load_raw()
    session_data = data.get(session_id)
    if not session_data:
        return False
    try:
        _restore_engine(engine, session_data)
        return True
    except Exception:
        return False


def save_engine_state(session_id: str, engine) -> None:
    """Persist the current engine state to file."""
    with _lock:
        data = _load_raw()
        data[session_id] = _serialize_engine(engine)
        _save_raw(data)


def delete_session(session_id: str) -> None:
    """Remove a completed/ended session. Safe to call even if it doesn't exist."""
    with _lock:
        data = _load_raw()
        data.pop(session_id, None)
        _save_raw(data)


def session_exists(session_id: str) -> bool:
    """Check whether a session has saved state."""
    with _lock:
        data = _load_raw()
    return session_id in data


def active_session_count() -> int:
    """Return number of sessions currently in sessions.json."""
    with _lock:
        data = _load_raw()
    return len(data)


# ── Lightweight wrappers (used by app.py) ────────────────────────────────────
# app.py calls load_state(session_id) → ConversationState
# and save_state(session_id, state) — these thin wrappers bridge the gap.

def load_state(session_id: str) -> ConversationState:
    """
    Load a ConversationState for a session_id.
    Returns a fresh ConversationState if no saved session exists.
    """
    with _lock:
        data = _load_raw()
    session_data = data.get(session_id)
    if not session_data:
        return ConversationState()
    state_data = session_data.get("state")
    if not state_data:
        return ConversationState()
    known = {f.name for f in fields(ConversationState)}
    clean = {k: v for k, v in state_data.items() if k in known}
    try:
        return ConversationState(**clean)
    except (TypeError, AttributeError):
        return ConversationState()


def save_state(session_id: str, state: ConversationState) -> None:
    """
    Persist a ConversationState for a session_id.
    Stores it in the same sessions.json format for compatibility.
    """
    with _lock:
        data = _load_raw()
        session_data = data.get(session_id, {})
        session_data["state"] = asdict(state)
        data[session_id] = session_data
        _save_raw(data)
