"""
api_handler.py
Handles all OpenAI API interactions with retry logic and JSON validation.
"""

import json
import re
import time
import openai
from state_machine import ConversationState, STATE_SYSTEM_PROMPTS, classify_lead, next_action, S5, S5_CLOSING, STATE_REQUIRED_QUESTION

MAX_RETRIES = 2
RETRY_DELAY = 1.5  # seconds


def _build_user_message(user_input: str, state: ConversationState) -> str:
    """Construct a detailed context message for the AI."""
    parts = [f"User said: {user_input}"]
    data = state.collected_data()

    if data["duration_months"] is not None:
        parts.append(f"Duration trying: {data['duration_months']} months")
    if data["age"] is not None:
        parts.append(f"Age: {data['age']}")
    if data["treatment_history"] is not None:
        parts.append(f"Treatment history: {data['treatment_history']}")

    lead = classify_lead(state)
    action = next_action(lead)
    parts.append(f"Current lead_score: {lead}")
    parts.append(f"Suggested action: {action}")
    parts.append(f"Current state: {state.current_state}")

    return "\n".join(parts)


def _extract_json(text: str) -> dict:
    """Extract and parse JSON from AI response, handling markdown fences."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()

    # Try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object via regex
    match = re.search(r'\{[^{}]*\}', cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract valid JSON from: {text[:200]}")


def _validate_response(data: dict, current_state: str) -> dict:
    """Validate required keys and sane values; fill defaults if missing."""
    required_keys = ["next_state", "response_text", "lead_score", "action"]
    for key in required_keys:
        if key not in data:
            raise ValueError(f"Missing key in AI response: {key}")

    valid_states   = ["S1", "S2", "S3", "S4", "S5"]
    valid_scores   = ["Hot", "Warm", "Cold"]
    valid_actions  = ["continue", "transfer", "end"]

    if data["next_state"] not in valid_states:
        data["next_state"] = current_state  # fall back to same state
    if data["lead_score"] not in valid_scores:
        data["lead_score"] = "Cold"
    if data["action"] not in valid_actions:
        data["action"] = "continue"

    # Enforce 20-word limit
    words = data["response_text"].split()
    if len(words) > 20:
        data["response_text"] = " ".join(words[:20]) + "…"

    return data


def call_openai(user_input: str, state: ConversationState, client: openai.OpenAI) -> dict:
    """
    Call OpenAI API with retry logic.
    Returns a validated dict with next_state, response_text, lead_score, action.
    """
    system_prompt = STATE_SYSTEM_PROMPTS[state.current_state]
    user_message  = _build_user_message(user_input, state)

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
                temperature=0.3,
                max_tokens=150,
            )
            raw_text = response.choices[0].message.content.strip()
            data = _extract_json(raw_text)
            data = _validate_response(data, state.current_state)
            return data

        except (openai.APIConnectionError, openai.APITimeoutError) as e:
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            continue

        except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
            raise RuntimeError(f"OpenAI authentication error: {e}") from e

        except (ValueError, KeyError) as e:
            last_error = e
            if attempt < MAX_RETRIES:
                # Ask model to fix its output
                system_prompt += (
                    "\n\nPREVIOUS RESPONSE WAS INVALID JSON. "
                    "You MUST return ONLY a valid JSON object. No other text."
                )
                continue

    # All retries exhausted — return a safe fallback
    return _fallback_response(state, str(last_error))


def _fallback_response(state: ConversationState, error_msg: str) -> dict:
    """Return a safe, deterministic fallback when AI fails.
    Uses exact required questions per state — no open-ended phrases."""
    lead = classify_lead(state)

    fallback_texts = {
        "S1": "Hi! I have 3 quick questions to understand how we can help. Is that okay?",
        "S2": STATE_REQUIRED_QUESTION["S2"],
        "S3": STATE_REQUIRED_QUESTION["S3"],
        "S4": STATE_REQUIRED_QUESTION["S4"],
        "S5": S5_CLOSING.get(lead, S5_CLOSING["Cold"]),
    }
    action = next_action(lead)
    # Determine next state: at S5 stay, otherwise advance
    state_order = ["S1", "S2", "S3", "S4", "S5"]
    idx = state_order.index(state.current_state)
    ns = state_order[min(idx, len(state_order) - 1)]  # stay on error

    return {
        "next_state": ns,
        "response_text": fallback_texts.get(state.current_state, "Could you repeat that?"),
        "lead_score": lead,
        "action": action if state.current_state == "S5" else "continue",
        "_fallback": True,
        "_error": error_msg,
    }
