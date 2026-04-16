"""
TwiML response builders. All <Play> URLs point to pre-generated MP3s so
Twilio can stream instantly.

Design notes:
  • Ack is played OUTSIDE the Gather (plays in full, prevents dead-air).
  • The actual question is INSIDE the Gather so the user can barge-in.
  • On gather timeout we Redirect back to /voice/respond with a flag,
    and the route replays the same state's question.
"""
from typing import List, Optional
from xml.sax.saxutils import escape
from app.config import (
    TWILIO_LANGUAGE, TWILIO_SPEECH_TIMEOUT, TWILIO_GATHER_TIMEOUT,
)


def _play_tags(urls: List[Optional[str]]) -> str:
    return "".join(f"<Play>{escape(u)}</Play>" for u in urls if u)


def build_gather(
    action_url: str,
    play_urls: List[Optional[str]],
    ack_url: Optional[str] = None,
    hints: Optional[str] = None,
    timeout_redirect_url: Optional[str] = None,
) -> str:
    """
    TwiML: optional ack (outside gather) + gather(question_play) + redirect on timeout.
    """
    pre = f"<Play>{escape(ack_url)}</Play>" if ack_url else ""
    inner = _play_tags(play_urls)
    hints_attr = f' hints="{escape(hints)}"' if hints else ""
    redirect_url = timeout_redirect_url or f"{action_url}?timeout=1"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"{pre}"
        f'<Gather input="speech" action="{escape(action_url)}" method="POST"'
        f' speechTimeout="{TWILIO_SPEECH_TIMEOUT}" timeout="{TWILIO_GATHER_TIMEOUT}"'
        f' language="{escape(TWILIO_LANGUAGE)}"{hints_attr}>'
        f"{inner}"
        "</Gather>"
        f'<Redirect method="POST">{escape(redirect_url)}</Redirect>'
        "</Response>"
    )


def build_play_and_hangup(
    play_urls: List[Optional[str]],
    ack_url: Optional[str] = None,
) -> str:
    """TwiML: optional ack + sequence of Play + Hangup."""
    pre = f"<Play>{escape(ack_url)}</Play>" if ack_url else ""
    inner = _play_tags(play_urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"{pre}"
        f"{inner}"
        "<Hangup/>"
        "</Response>"
    )
