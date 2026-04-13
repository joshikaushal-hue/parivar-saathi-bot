"""
main.py
IVF Conversation Engine — Unified AI-powered version (v2.0)

Uses state_machine.py (S1–S6) for conversation flow,
api_handler.py for OpenAI calls (S1–S4),
input_parser.py for deterministic data extraction,
and deterministic closing logic for S5–S6.

Usage:
    from main import IVFConversationEngine

    engine = IVFConversationEngine(client=openai_client, session_id="abc")
    result = engine.process_turn("Hi, I've been trying for 2 years")
"""

import re
import logging

from state_machine import (
    ConversationState, classify_lead, next_action,
    S1, S2, S3, S4, S5, S6,
    ACTION_CONTINUE, ACTION_TRANSFER, ACTION_END,
    LEAD_HOT, LEAD_WARM, LEAD_COLD,
    S5_CLOSING, S5_CONFIRM, S5_SOFT_RETRY, S5_GRACEFUL_END, S5_MAX_ATTEMPTS,
    S6_ASK_PHONE, S6_CONFIRM, S6_INVALID_PHONE,
    classify_s5_intent,
)
from api_handler import call_openai
from input_parser import (
    is_s1_refusal, parse_duration_months, parse_age,
    parse_treatment, extract_phone,
)

log = logging.getLogger("ivf_engine")


class IVFConversationEngine:
    """
    State-driven IVF lead qualification engine.

    States:
        S1 — Greeting / consent
        S2 — Duration (how long trying to conceive)
        S3 — Age
        S4 — Treatment history
        S5 — Closing (offer counselor connection)
        S6 — Phone number capture
    """

    def __init__(self, client, session_id: str = ""):
        self.client = client
        self.session_id = session_id
        self.state = ConversationState()

    def process_turn(self, user_input: str) -> dict:
        """
        Process one user message. Returns:
            {
                "next_state": str,
                "response_text": str,
                "lead_score": str,
                "action": str,
            }
        """
        user_input = user_input.strip()
        self.state.turn_count += 1

        cs = self.state.current_state

        # ── S1: Greeting / Consent ───────────────────────────────────────────
        if cs == S1:
            return self._handle_s1(user_input)

        # ── S2: Duration ─────────────────────────────────────────────────────
        if cs == S2:
            return self._handle_s2(user_input)

        # ── S3: Age ──────────────────────────────────────────────────────────
        if cs == S3:
            return self._handle_s3(user_input)

        # ── S4: Treatment history ────────────────────────────────────────────
        if cs == S4:
            return self._handle_s4(user_input)

        # ── S5: Closing (offer counselor) ────────────────────────────────────
        if cs == S5:
            return self._handle_s5(user_input)

        # ── S6: Phone capture ────────────────────────────────────────────────
        if cs == S6:
            return self._handle_s6(user_input)

        # Fallback — should not happen
        return self._result(S1, "Something went wrong. Let's start over.", LEAD_COLD, ACTION_END)

    def is_complete(self) -> bool:
        """True if conversation has ended (action = end or transfer at S5/S6)."""
        return self.state.action in (ACTION_END, ACTION_TRANSFER) and \
               self.state.current_state in (S5, S6)

    # ── State handlers ───────────────────────────────────────────────────────

    def _handle_s1(self, user_input: str) -> dict:
        """S1: Check consent. If user refuses → end. Otherwise → S2."""
        if is_s1_refusal(user_input):
            self.state.current_state = S1
            self.state.action = ACTION_END
            return self._result(
                S1,
                "No problem at all. We're here whenever you need us. Take care.",
                LEAD_COLD,
                ACTION_END,
            )

        # Use AI to generate a natural S1 response
        S1_FALLBACK = (
            "Hi! I'm the Parivar Saathi assistant. "
            "I have 3 quick questions to understand how we can help. "
            "How long have you been trying to conceive?"
        )
        result = self._call_ai(user_input)

        # Always advance to S2 on non-refusal
        self.state.current_state = S2
        self.state.action = ACTION_CONTINUE

        response_text = result.get("response_text", S1_FALLBACK)
        # If AI returned a generic fallback, use our branded one instead
        if response_text == "Could you repeat that?":
            response_text = S1_FALLBACK

        return self._result(S2, response_text, LEAD_COLD, ACTION_CONTINUE)

    def _handle_s2(self, user_input: str) -> dict:
        """S2: Extract duration. If captured → S3. If bare number → wait for unit."""
        # Check for bare number (needs clarification: months or years?)
        bare_num = re.match(r'^(\d+\.?\d*)$', user_input.strip())
        if bare_num and self.state.pending_duration_number is None:
            self.state.pending_duration_number = float(bare_num.group(1))
            return self._result(
                S2,
                "Just to confirm — is that months or years?",
                self._current_lead_score(),
                ACTION_CONTINUE,
            )

        # If we had a pending bare number and now user says months/years
        if self.state.pending_duration_number is not None:
            unit_text = user_input.lower().strip()
            num = self.state.pending_duration_number
            if any(w in unit_text for w in ["year", "sal", "saal", "yr"]):
                self.state.duration_months = num * 12
            elif any(w in unit_text for w in ["month", "mahine", "mahe"]):
                self.state.duration_months = num
            else:
                # Assume months if unclear
                self.state.duration_months = num
            self.state.pending_duration_number = None
            self.state.current_state = S3
            self.state.lead_score = classify_lead(self.state)
            return self._result(
                S3,
                "Noted. How old are you, or roughly what age range?",
                self.state.lead_score,
                ACTION_CONTINUE,
            )

        # Try deterministic extraction first
        dur = parse_duration_months(user_input)
        if dur is not None:
            self.state.duration_months = dur
            self.state.current_state = S3
            self.state.lead_score = classify_lead(self.state)
            return self._result(
                S3,
                "Noted. How old are you, or roughly what age range?",
                self.state.lead_score,
                ACTION_CONTINUE,
            )

        # Fall back to AI
        result = self._call_ai(user_input)
        if result.get("next_state") == S3 and self.state.duration_months is None:
            # AI thinks it captured duration but parser didn't — trust AI, estimate
            self.state.duration_months = 12.0  # default estimate
        if result.get("next_state") == S3:
            self.state.current_state = S3
        return self._result(
            self.state.current_state,
            result.get("response_text", "How long have you been trying to conceive — months or years?"),
            self._current_lead_score(),
            ACTION_CONTINUE,
        )

    def _handle_s3(self, user_input: str) -> dict:
        """S3: Extract age. If captured → S4."""
        age = parse_age(user_input)
        if age is not None:
            self.state.age = age
            self.state.current_state = S4
            self.state.lead_score = classify_lead(self.state)
            return self._result(
                S4,
                "Noted. Have you tried any fertility treatments — IUI, IVF, or none at all?",
                self.state.lead_score,
                ACTION_CONTINUE,
            )

        # Fall back to AI
        result = self._call_ai(user_input)
        if result.get("next_state") == S4:
            if self.state.age is None:
                self.state.age = user_input.strip()  # store raw if parser missed
            self.state.current_state = S4
        return self._result(
            self.state.current_state,
            result.get("response_text", "How old are you, or roughly what age range?"),
            self._current_lead_score(),
            ACTION_CONTINUE,
        )

    def _handle_s4(self, user_input: str) -> dict:
        """S4: Extract treatment history. If captured → S5."""
        treatment = parse_treatment(user_input)
        if treatment is not None:
            self.state.treatment_history = treatment
            self.state.current_state = S5
            self.state.lead_score = classify_lead(self.state)
            self.state.closing_attempt_count = 1
            closing_msg = S5_CLOSING.get(self.state.lead_score, S5_CLOSING[LEAD_COLD])
            # CRITICAL: Always use CONTINUE when first showing S5 closing.
            # The action (transfer/end) is set AFTER the user responds in _handle_s5.
            # Otherwise is_complete() fires early and session gets deleted.
            return self._result(S5, closing_msg, self.state.lead_score, ACTION_CONTINUE)

        # Fall back to AI
        result = self._call_ai(user_input)
        if result.get("next_state") == S5:
            if self.state.treatment_history is None:
                self.state.treatment_history = user_input.strip()
            self.state.current_state = S5
            self.state.lead_score = classify_lead(self.state)
            self.state.closing_attempt_count = 1
            closing_msg = S5_CLOSING.get(self.state.lead_score, S5_CLOSING[LEAD_COLD])
            return self._result(S5, closing_msg, self.state.lead_score, ACTION_CONTINUE)

        return self._result(
            self.state.current_state,
            result.get("response_text", "Have you tried any fertility treatments — IUI, IVF, or none at all?"),
            self._current_lead_score(),
            ACTION_CONTINUE,
        )

    def _handle_s5(self, user_input: str) -> dict:
        """S5: Closing logic. Yes → S6 (capture phone) or confirm. No → retry or end."""
        intent = classify_s5_intent(user_input)
        lead = self.state.lead_score

        if intent == "yes":
            # Hot/Warm → capture phone number in S6
            if lead in (LEAD_HOT, LEAD_WARM):
                self.state.current_state = S6
                self.state.action = ACTION_CONTINUE
                return self._result(S6, S6_ASK_PHONE, lead, ACTION_CONTINUE)
            # Cold → confirm and end
            self.state.action = ACTION_END
            return self._result(S5, S5_CONFIRM, lead, ACTION_END)

        if intent == "no":
            self.state.closing_attempt_count += 1
            if self.state.closing_attempt_count >= S5_MAX_ATTEMPTS:
                self.state.action = ACTION_END
                return self._result(S5, S5_GRACEFUL_END, lead, ACTION_END)
            return self._result(S5, S5_SOFT_RETRY, lead, ACTION_CONTINUE)

        # Unclear — treat as soft no, offer retry
        self.state.closing_attempt_count += 1
        if self.state.closing_attempt_count >= S5_MAX_ATTEMPTS:
            self.state.action = ACTION_END
            return self._result(S5, S5_GRACEFUL_END, lead, ACTION_END)
        return self._result(S5, S5_SOFT_RETRY, lead, ACTION_CONTINUE)

    def _handle_s6(self, user_input: str) -> dict:
        """S6: Capture phone number. Valid → end with transfer. Invalid → re-ask."""
        phone = extract_phone(user_input)
        lead = self.state.lead_score

        if phone:
            self.state.phone_number = phone
            self.state.action = ACTION_TRANSFER
            return self._result(S6, S6_CONFIRM, lead, ACTION_TRANSFER)

        # Invalid phone — re-ask
        return self._result(S6, S6_INVALID_PHONE, lead, ACTION_CONTINUE)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _call_ai(self, user_input: str) -> dict:
        """Call OpenAI via api_handler. Returns parsed response dict."""
        try:
            return call_openai(user_input, self.state, self.client)
        except Exception as e:
            log.error(f"OpenAI call failed: {e}", exc_info=True)
            return {
                "next_state": self.state.current_state,
                "response_text": "Could you repeat that?",
                "lead_score": self._current_lead_score(),
                "action": ACTION_CONTINUE,
            }

    def _current_lead_score(self) -> str:
        """Recalculate and cache lead score."""
        self.state.lead_score = classify_lead(self.state)
        return self.state.lead_score

    def _result(self, next_state: str, response_text: str,
                lead_score: str, action: str) -> dict:
        """Build the standard return dict and update internal state."""
        self.state.current_state = next_state
        self.state.action = action
        self.state.lead_score = lead_score
        return {
            "next_state": next_state,
            "response_text": response_text,
            "lead_score": lead_score,
            "action": action,
        }
