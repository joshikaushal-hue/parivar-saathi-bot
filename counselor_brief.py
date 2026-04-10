"""
counselor_brief.py
Lead Intelligence Report Generator — v1.0

Generates a structured counselor brief for each qualified lead.
Fully deterministic — no AI call needed.

Output structure:
  - snapshot           : one-line patient summary
  - severity_tag       : clinical label
  - priority_action    : clear first step with timing
  - emotional_insight  : how the patient likely feels
  - conversation_strategy : list of tactics for this lead type
  - objection_handling : pre-mapped responses to common objections
  - urgency_flags      : list of clinical / demographic signals
"""

from typing import Optional, List
from lead_scorer import LeadProfile, score_lead


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def generate_brief(
    duration_months: Optional[float],
    age: Optional[str],
    treatment_history: Optional[str],
    phone: Optional[str] = None,
    session_id: str = "",
) -> dict:
    """
    Returns a fully structured Lead Intelligence Report dict.
    Called once when a lead reaches S5 (closing stage).
    """
    profile = score_lead(duration_months, age, treatment_history)
    th = (treatment_history or "none").strip()

    return {
        "session_id":            session_id,
        "phone":                 phone,
        "lead_score":            profile.score,
        "priority_rank":         profile.priority_rank,
        "severity_tag":          profile.severity_tag,
        "ivf_probability":       profile.ivf_probability,
        "ovarian_reserve_risk":  profile.ovarian_reserve_concern,
        "follow_up_hours":       profile.follow_up_hours,
        "snapshot":              _build_snapshot(duration_months, age, th, profile),
        "emotional_insight":     _build_emotional_insight(profile, duration_months, age, th),
        "conversation_strategy": _build_strategy(profile, th),
        "objection_handling":    _build_objection_map(profile, th),
        "priority_action":       _build_priority_action(profile),
        "urgency_flags":         profile.urgency_flags,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_snapshot(dur_months, age, treatment, profile: LeadProfile) -> str:
    dur_text = _format_duration(dur_months)
    parts = [f"Trying for {dur_text}"]
    if age:
        parts.append(f"age {age}")
    if treatment.lower() not in ("none", ""):
        parts.append(f"treatment: {treatment}")
    else:
        parts.append("no prior treatment")
    parts.append(profile.severity_tag)
    return " | ".join(parts)


def _build_emotional_insight(profile: LeadProfile, dur_months, age, treatment) -> str:
    th = treatment.lower()
    dur = dur_months or 0

    if "fail" in th and "ivf" in th:
        return (
            "Patient has experienced IVF failure — likely carrying grief, self-doubt, "
            "and financial fatigue. Approach with deep empathy. Avoid promises and "
            "false hope. Acknowledge the journey before discussing next steps."
        )
    if "ivf" in th:
        return (
            "Has undergone IVF — emotionally invested and likely comparing options. "
            "They are informed but may be cautious or guarded. "
            "Build trust before presenting your clinic's approach."
        )
    if "iui" in th:
        return (
            "Has tried IUI — aware of the process, may be frustrated with slow progress. "
            "Ready to hear about escalation options. Be direct and solution-focused."
        )
    if dur > 36:
        return (
            "Long infertility journey — likely exhausted, may have tried natural methods. "
            "Heavy emotional load. Open with acknowledgement; avoid rushing to close."
        )
    if dur >= 24:
        return (
            "2+ years of trying without success — motivation may be wavering. "
            "Needs a concrete plan more than reassurance. Give them direction."
        )
    if dur >= 12:
        return (
            "1+ year in — concern is growing but hope remains. "
            "Receptive to evaluation and guidance. Strong conversion window."
        )
    if profile.ovarian_reserve_concern:
        return (
            "Age-related urgency present. Patient may not be aware of the biological "
            "timeline. Educate sensitively — informed urgency is helpful, panic is not."
        )
    return (
        "Early stage — may not yet see themselves as needing medical help. "
        "Focus on normalisation and education. Do not oversell IVF."
    )


def _build_strategy(profile: LeadProfile, treatment: str) -> List[str]:
    th = treatment.lower()

    if "fail" in th and "ivf" in th:
        return [
            "Open: 'I understand you've been through a lot — we want to review your case carefully.'",
            "Ask about their IVF protocol and previous clinic experience before suggesting anything.",
            "Do NOT mention success rates immediately — it builds resentment.",
            "Focus on 'personalised protocol' and 'fresh approach' language.",
            "Cost objection response: 'We can review what's involved and design a plan that fits your situation.'",
        ]
    if "ivf" in th:
        return [
            "Don't explain IVF basics — they already know. Acknowledge their experience.",
            "Ask: 'What was your experience like?' before presenting your clinic.",
            "Differentiate: protocol customisation, doctor attention, support system.",
            "Second-opinion response: 'Many patients come to us for a second opinion — that's completely normal.'",
        ]
    if "iui" in th:
        return [
            "Validate: 'IUI is a good first step — many couples then move to IVF with good results.'",
            "Suggest a consultation to review IUI cycles and assess IVF readiness.",
            "Delay mindset: 'Waiting without changing the approach rarely helps — let's review your options.'",
        ]
    if profile.priority_rank <= 2:
        return [
            "Lead with empathy: 'After so long, I can imagine how overwhelming this feels.'",
            "Be direct about the next step: fertility workup + specialist consultation.",
            "Avoid generic reassurance — they have heard it. Offer a concrete plan.",
            "Cost objection: 'Let's first understand what's needed — the right approach depends on your case.'",
        ]
    if profile.priority_rank <= 4:
        return [
            "Frame as information gathering: 'A consultation simply helps us understand where you stand.'",
            "Position as low-commitment first step — not a sales pitch.",
            "Soft close: 'Would you be open to a call with our specialist this week?'",
        ]
    return [
        "Reassure without medicalising: 'Many couples conceive naturally in the first year — this is still early.'",
        "Offer a free information session or lifestyle guidance.",
        "Plant a future seed: 'If things don't progress in 3–6 months, we're here to help.'",
        "Do NOT push IVF — premature and counterproductive at this stage.",
    ]


def _build_objection_map(profile: LeadProfile, treatment: str) -> dict:
    """Pre-mapped responses for the 5 most common IVF patient objections."""
    th = treatment.lower()

    cost = (
        "Acknowledge the concern: 'IVF costs are significant — we understand that.' "
        "Then pivot: 'We offer flexible payment plans and can advise on insurance coverage. "
        "Let's first check what protocol is right for you, then discuss costs transparently.'"
    )
    delay = (
        "Gently challenge: 'I understand wanting to wait — but time is one factor we cannot "
        "recover. A consultation costs nothing and gives you clarity whether to act now or later.'"
    )
    fear = (
        "Normalise: 'Fear of failure is completely natural — most of our patients felt the same. "
        "We can walk you through realistic expectations for your specific situation.'"
        if "fail" not in th else
        "Validate deeply: 'What you went through was hard. We will look at exactly what happened "
        "and what can be done differently. You deserve answers, not just another attempt.'"
    )
    second_opinion = (
        "Welcome it: 'Getting a second opinion is a sign of a well-informed patient. "
        "We are happy to review your previous reports and give you an honest assessment.'"
    )
    partner = (
        "Involve them: 'Could your partner join the call? Both of you understanding "
        "the options makes the decision much easier.' If not possible: "
        "'I can send you a summary to share with your partner at your own time.'"
    )

    return {
        "cost_objection":           cost,
        "delay_mindset":            delay,
        "fear_of_failure":          fear,
        "second_opinion_seeker":    second_opinion,
        "partner_not_aligned":      partner,
    }


def _build_priority_action(profile: LeadProfile) -> str:
    if profile.priority_rank == 1:
        return (
            f"⚡ CALL WITHIN {profile.follow_up_hours} HOURS — "
            f"High-value lead ({profile.severity_tag}). Assign senior counselor."
        )
    if profile.priority_rank == 2:
        return (
            f"📞 Call within {profile.follow_up_hours} hours. "
            f"Schedule specialist consultation. ({profile.severity_tag})"
        )
    if profile.priority_rank == 3:
        return (
            f"📞 Call within {profile.follow_up_hours} hours. "
            f"Offer fertility workup consultation. ({profile.severity_tag})"
        )
    if profile.priority_rank == 4:
        return (
            f"💬 Follow up within {profile.follow_up_hours} hours. "
            f"Soft outreach — information focus. ({profile.severity_tag})"
        )
    return (
        f"📲 Send WhatsApp education message. "
        f"Follow up in {profile.follow_up_hours} hours if no response. ({profile.severity_tag})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _format_duration(months: Optional[float]) -> str:
    if months is None:
        return "unknown duration"
    if months < 12:
        return f"{int(months)} month(s)"
    years = months / 12
    if years == int(years):
        return f"{int(years)} year(s)"
    return f"{years:.1f} years"
