"""
Deterministic state machine. No LLM. Pure functions of (session, input).
"""
from typing import Dict, Any
from app.state_machine.states import State, next_state_of
from app.state_machine.validators import (
    parse_age,
    parse_duration_months,
    parse_treatment,
)
from app.models.session import Session
from app.services.scoring import score_lead


def process_input(session: Session, speech_text: str) -> Dict[str, Any]:
    """
    Mutate session based on speech input at the CURRENT state.

    Returns:
        {
          "next_state": State,   # where we should go next
          "retry": bool,         # True if input was unparseable at current state
          "done": bool,          # True if flow is complete
        }
    """
    state = State(session.current_state)
    result: Dict[str, Any] = {"next_state": state, "retry": False, "done": False}

    if state == State.GREETING:
        # Greeting has no question — always advance
        result["next_state"] = State.ASK_AGE

    elif state == State.ASK_AGE:
        age = parse_age(speech_text or "")
        if age is None:
            session.retry_count += 1
            result["retry"] = True
        else:
            session.lead.age = age
            session.retry_count = 0
            result["next_state"] = State.ASK_DURATION

    elif state == State.ASK_DURATION:
        months = parse_duration_months(speech_text or "")
        if months is None:
            session.retry_count += 1
            result["retry"] = True
        else:
            session.lead.duration_months = months
            session.retry_count = 0
            result["next_state"] = State.ASK_TREATMENT

    elif state == State.ASK_TREATMENT:
        tx = parse_treatment(speech_text or "")
        if tx is None:
            session.retry_count += 1
            result["retry"] = True
        else:
            session.lead.prior_ivf = tx["prior_ivf"]
            session.lead.prior_treatments = tx["treatments"]
            session.retry_count = 0
            result["next_state"] = State.QUALIFY

    elif state == State.QUALIFY:
        # Score now, then move to CLOSE
        score, category = score_lead(session.lead)
        session.score = score
        session.category = category
        result["next_state"] = State.CLOSE

    elif state == State.CLOSE:
        result["next_state"] = State.END
        result["done"] = True

    # On success, advance the session's current_state
    if not result["retry"]:
        session.current_state = result["next_state"].value
        session.touch()

    return result


def force_advance(session: Session) -> State:
    """
    Called when retry budget is exhausted for the current state — we drop
    the unknown field and move on.
    """
    current = State(session.current_state)
    nxt = next_state_of(current)
    session.retry_count = 0
    session.current_state = nxt.value

    # If we advance into QUALIFY, score immediately and roll into CLOSE
    if nxt == State.QUALIFY:
        score, category = score_lead(session.lead)
        session.score = score
        session.category = category
        session.current_state = State.CLOSE.value
        return State.CLOSE

    session.touch()
    return nxt
