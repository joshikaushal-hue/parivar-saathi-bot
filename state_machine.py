"""
state_machine.py
Defines the IVF conversation state machine: states, transitions, and lead scoring.
v2.0 — Uses lead_scorer.py for composite scoring.
"""

from dataclasses import dataclass, field
from typing import Optional
from lead_scorer import score_lead

# State constants
S1 = "S1"
S2 = "S2"
S3 = "S3"
S4 = "S4"
S5 = "S5"
S6 = "S6"   # Lead capture — phone number collection

VALID_STATES = [S1, S2, S3, S4, S5, S6]

LEAD_HOT  = "Hot"
LEAD_WARM = "Warm"
LEAD_COLD = "Cold"

ACTION_CONTINUE  = "continue"
ACTION_TRANSFER  = "transfer"
ACTION_END       = "end"


@dataclass
class ConversationState:
    current_state: str = S1
    duration_months: Optional[float] = None   # normalized to months
    age: Optional[str] = None
    treatment_history: Optional[str] = None
    phone_number: Optional[str] = None        # captured in S6
    lead_score: str = LEAD_COLD
    action: str = ACTION_CONTINUE
    turn_count: int = 0
    retry_same_state: bool = False             # flag to re-ask same question
    closing_attempt_count: int = 0             # tracks S5 closing exchanges (0=not shown yet)
    pending_duration_number: Optional[float] = None  # bare number awaiting unit in S2

    def collected_data(self) -> dict:
        return {
            "duration_months": self.duration_months,
            "age": self.age,
            "treatment_history": self.treatment_history,
            "phone_number": self.phone_number,
        }


def classify_lead(state: ConversationState) -> str:
    """
    v2.0 — Uses composite lead_scorer for clinical-grade scoring.
    Still returns "Hot" | "Warm" | "Cold" so existing flow is unchanged.

    Scoring factors (in priority order):
      1. Treatment history (IVF failure → Hot immediately)
      2. Duration (>3 years → Hot, 1–3 years → Warm, <1 year → Cold)
      3. Age modifier (≥35 escalates priority)
    """
    profile = score_lead(
        duration_months=state.duration_months,
        age=state.age,
        treatment_history=state.treatment_history,
    )
    return profile.score


def next_action(lead_score: str) -> str:
    if lead_score == LEAD_HOT:
        return ACTION_TRANSFER
    if lead_score == LEAD_WARM:
        return ACTION_CONTINUE
    return ACTION_END


# ── S5 closing messages — conversion-layer v2.0 ───────────────────────────────
# Hot: Create informed urgency. Acknowledge journey + time sensitivity.
# Warm: Normalise + give clear next step. Reduce friction.
# Cold: Reassure + plant seed. Don't medicalise.
S5_CLOSING = {
    LEAD_HOT: (
        "Given your journey, a specialist review sooner rather than later can make a real difference. "
        "Our counselor can call you — morning or evening?"
    ),
    LEAD_WARM: (
        "At this stage, a counselling session gives you clarity — not commitment. "
        "Our counsellor can reach you shortly. Does that work?"
    ),
    LEAD_COLD: (
        "You're still early in the journey — many couples conceive naturally. "
        "We're here whenever you need guidance. Want us to check in with you?"
    ),
}

# ── S5: user says yes/ok → confirm and end ────────────────────────────────────
S5_CONFIRM = "Our counselor will contact you shortly. Take care."

# ── S5: user says no (first time) → softer alternative ───────────────────────
S5_SOFT_RETRY = (
    "Understood. If it helps, you can also reach us on WhatsApp anytime — "
    "no pressure. Would a call later this week suit you better?"
)

# ── S5: user says no again (second time) → graceful end ──────────────────────
S5_GRACEFUL_END = (
    "That's completely okay. We're here whenever you're ready — "
    "our WhatsApp is open 24/7. Take care of yourself."
)

# Maximum closing exchanges before forcing end
# Flow: closing shown (count=1) → "no" → soft retry (count=2) → "no" → graceful end (count=3 >= 3)
S5_MAX_ATTEMPTS = 3

# ── S6: Lead capture responses (deterministic, no AI) ────────────────────────
S6_ASK_PHONE     = "May I have your phone number so our counselor can reach you?"
S6_CONFIRM       = "Our counselor will contact you shortly. Take care."
S6_INVALID_PHONE = "Could you share a valid phone number? At least 8 digits."

# ── S5 user-intent classifier (deterministic, no AI needed) ──────────────────
_YES_TOKENS = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "alright",
    "haan", "haa", "ji", "theek", "theek hai", "bilkul", "zaroor",
    "morning", "evening", "afternoon",   # time preference = yes for Hot
    "please", "go ahead", "confirm", "agreed", "sounds good",
}
_NO_TOKENS = {
    "no", "nope", "nahi", "na", "not now", "later", "not interested",
    "abhi nahi", "baad mein", "mat karo", "rehne do", "not today",
    "maybe later", "not yet", "no thanks",
}

def classify_s5_intent(user_input: str) -> str:
    """
    Returns 'yes', 'no', or 'unclear' based on user response during S5 closing.
    Deterministic — no AI call needed.
    """
    text = user_input.lower().strip()
    # Check multi-word phrases first
    for token in sorted(_NO_TOKENS, key=len, reverse=True):
        if token in text:
            return "no"
    for token in sorted(_YES_TOKENS, key=len, reverse=True):
        if token in text:
            return "yes"
    return "unclear"

# ── Required question each state MUST end with if data not yet captured ────────
STATE_REQUIRED_QUESTION = {
    S2: "How long have you been trying to conceive — months or years?",
    S3: "How old are you, or roughly what age range?",
    S4: "Have you tried any fertility treatments — IUI, IVF, or none at all?",
}

STATE_SYSTEM_PROMPTS = {
    S1: (
        "You are an IVF intake assistant. This is a structured intake form, not a chat. "
        "State S1 — Intro. Your ONLY job: greet briefly and ask if it is okay to continue. "
        "Do NOT ask any other question. Do NOT offer help. Do NOT explain the process. "
        "BANNED: 'How can I assist', 'Let's talk', 'journey', 'Certainly', 'Of course', 'Great'. "
        "RULE: Response must be under 20 words and end with a yes/no question. "
        "Output ONLY valid JSON, no extra text:\n"
        '{"next_state":"S2","response_text":"...","lead_score":"Cold","action":"continue"}'
    ),
    S2: (
        "You are an IVF intake assistant running a structured intake form. "
        "State S2 — ONE job only: capture how long the caller has been trying to conceive. "
        "\n"
        "DECISION RULES (apply in order):\n"
        "1. If context shows 'Duration trying: X months' — the data is captured. Move to S3. "
        "   Response: 1 short acknowledgement word ('Noted.' or 'Understood.') + ask age question: "
        "   'How old are you, or roughly what age range?'\n"
        "2. If user gave a clear duration (e.g. '2 years', '8 months') — treat as captured. Move to S3. "
        "   Response: same pattern as rule 1.\n"
        "3. If user gave a vague duration (e.g. 'a while', 'some time', 'kafi time se') — stay at S2. "
        "   Response: 'Could you be more specific — months or years?'\n"
        "4. If user asked a question or gave unrelated input — stay at S2. "
        "   Response: max 4 words addressing it, then IMMEDIATELY: "
        "   'How long have you been trying to conceive — months or years?'\n"
        "5. If user expressed emotion or distress — stay at S2. "
        "   Response: exactly 1 empathy phrase (max 5 words), then IMMEDIATELY ask the duration question.\n"
        "\n"
        "BANNED PHRASES: 'How can I assist', 'Let's talk further', 'journey', "
        "'Thank you for sharing', 'Great', 'next step', 'let me help'. "
        "RULE: Under 20 words total. NEVER end without either moving to S3 or re-asking the duration question. "
        "Output ONLY valid JSON, no extra text:\n"
        '{"next_state":"S2 or S3","response_text":"...","lead_score":"Hot/Warm/Cold","action":"continue"}'
    ),
    S3: (
        "You are an IVF intake assistant running a structured intake form. "
        "State S3 — ONE job only: capture the caller's age or age range. "
        "\n"
        "DECISION RULES (apply in order):\n"
        "1. If context shows 'Age: X' — the data is captured. Move to S4. "
        "   Response: 1 short acknowledgement word + ask treatment question: "
        "   'Have you tried any fertility treatments — IUI, IVF, or none at all?'\n"
        "2. If user gave a clear age or age range (e.g. '32', '30-35', 'mid thirties') — treat as captured. Move to S4. "
        "   Response: same pattern as rule 1.\n"
        "3. If user gave unrelated input or asked a question — stay at S3. "
        "   Response: max 4 words, then IMMEDIATELY: 'How old are you, or roughly what age range?'\n"
        "4. If user expressed emotion or distress — stay at S3. "
        "   Response: exactly 1 empathy phrase (max 5 words), then IMMEDIATELY ask the age question.\n"
        "\n"
        "BANNED PHRASES: 'How can I assist', 'Let's talk further', 'Thank you for sharing', "
        "'Great', 'next step', 'journey'. "
        "RULE: Under 20 words total. NEVER end without either moving to S4 or re-asking the age question. "
        "Output ONLY valid JSON, no extra text:\n"
        '{"next_state":"S3 or S4","response_text":"...","lead_score":"Hot/Warm/Cold","action":"continue"}'
    ),
    S4: (
        "You are an IVF intake assistant running a structured intake form. "
        "State S4 — ONE job only: capture prior fertility treatment history. "
        "\n"
        "DECISION RULES (apply in order):\n"
        "1. If context shows 'Treatment history: X' — the data is captured. Move to S5. "
        "   Response: 1 short acknowledgement word only (e.g. 'Noted.'). Do NOT ask another question.\n"
        "2. If user clearly mentioned IUI, IVF, multiple failures, or no treatment — treat as captured. Move to S5. "
        "   Response: same pattern as rule 1.\n"
        "3. If user gave a vague answer (e.g. 'some treatments', 'a few things', 'tried something') — stay at S4. "
        "   Response: 'Which specifically — IUI, IVF, or none?'\n"
        "4. If user gave unrelated input or asked a question — stay at S4. "
        "   Response: max 4 words, then IMMEDIATELY: "
        "   'Have you tried any fertility treatments — IUI, IVF, or none at all?'\n"
        "5. If user expressed emotion or distress — stay at S4. "
        "   Response: exactly 1 empathy phrase (max 5 words), then IMMEDIATELY ask the treatment question.\n"
        "\n"
        "BANNED PHRASES: 'How can I assist', 'Let's talk further', 'Thank you for sharing', "
        "'Great', 'next step', 'journey', 'let me help'. "
        "RULE: Under 20 words total. NEVER end without either moving to S5 or re-asking the treatment question. "
        "Output ONLY valid JSON, no extra text:\n"
        '{"next_state":"S4 or S5","response_text":"...","lead_score":"Hot/Warm/Cold","action":"continue"}'
    ),
    S5: (
        "You are an IVF intake assistant. State S5 — Closing. "
        "The lead_score is provided in context. Use EXACTLY one of these lines, verbatim:\n"
        "Hot  → 'We recommend scheduling a counselling session soon. Would you prefer morning or evening?'\n"
        "Warm → 'A counselling session can help clarify next steps. Our counsellor will connect with you to take it forward.'\n"
        "Cold → 'It's still early days — many conceive naturally within the first year. We're here when you need us.'\n"
        "Do NOT add anything before or after. Do NOT paraphrase. Do NOT ask a follow-up. "
        "BANNED: 'How can I assist', 'Let's talk further', 'Thank you for sharing', 'journey'. "
        "Output ONLY valid JSON, no extra text:\n"
        '{"next_state":"S5","response_text":"...","lead_score":"Hot/Warm/Cold","action":"transfer/continue/end"}'
    ),
}
