"""
logger.py
Handles conversation logging to JSON-lines log file.
"""

import json
import os
from datetime import datetime

LOG_DIR  = "logs"
LOG_FILE = os.path.join(LOG_DIR, "conversations.jsonl")


def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def log_turn(session_id: str, turn: int, user_input: str,
             state: str, response: dict):
    """Append a single conversation turn to the log file."""
    ensure_log_dir()
    entry = {
        "session_id":  session_id,
        "timestamp":   datetime.utcnow().isoformat() + "Z",
        "turn":        turn,
        "state":       state,
        "user_input":  user_input,
        "response":    response,
        "lead_score":  response.get("lead_score"),
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_session_summary(session_id: str, collected_data: dict,
                        final_lead: str, final_action: str):
    """Append a session-end summary."""
    ensure_log_dir()
    entry = {
        "session_id":    session_id,
        "timestamp":     datetime.utcnow().isoformat() + "Z",
        "event":         "SESSION_END",
        "collected_data": collected_data,
        "final_lead":    final_lead,
        "final_action":  final_action,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
