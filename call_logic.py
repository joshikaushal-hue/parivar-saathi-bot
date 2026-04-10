"""
call_logic.py
AI Call Decision Tree — v1.0

Non-linear decision tree for IVF AI calling agent.
Handles the 5 most common objection patterns with adaptive branches.

Usage:
    from call_logic import get_call_script, handle_objection

    # Get opening script for a lead
    script = get_call_script(lead_score="Hot", treatment="IVF failure")

    # Handle a detected objection
    response = handle_objection("cost", lead_score="Warm", prior_treatment="IUI")
"""

from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Objection types
# ─────────────────────────────────────────────────────────────────────────────
OBJECTION_COST           = "cost"
OBJECTION_DELAY          = "delay"
OBJECTION_FEAR           = "fear"
OBJECTION_SECOND_OPINION = "second_opinion"
OBJECTION_PARTNER        = "partner"
OBJECTION_NOT_INTERESTED = "not_interested"

# Keywords to detect each objection in caller speech
OBJECTION_KEYWORDS = {
    OBJECTION_COST: [
        "expensive", "costly", "afford", "cost", "price", "fees",
        "paisa", "paise", "mehenga", "budget", "money", "payment",
    ],
    OBJECTION_DELAY: [
        "wait", "later", "not now", "try more", "baad mein", "abhi nahi",
        "kuch time aur", "few more months", "next year", "not ready",
    ],
    OBJECTION_FEAR: [
        "scared", "afraid", "fear", "darr", "dar", "failed before",
        "what if", "not sure", "nervous", "worried", "tension",
    ],
    OBJECTION_SECOND_OPINION: [
        "other doctor", "another clinic", "second opinion", "dusra doctor",
        "already consulted", "comparing", "thinking about other",
    ],
    OBJECTION_PARTNER: [
        "husband", "wife", "partner", "spouse", "not sure yet", "discuss",
        "tell them", "ask them", "together", "pati", "patni",
    ],
    OBJECTION_NOT_INTERESTED: [
        "not interested", "don't want", "nahi chahiye", "no thanks",
        "hang up", "remove my number", "don't call",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Opening scripts — based on lead score + treatment history
# ─────────────────────────────────────────────────────────────────────────────

def get_call_script(lead_score: str, treatment: Optional[str] = None) -> dict:
    """
    Returns the opening call script for a given lead profile.

    Returns:
        {
            "opening": str,       – first thing AI says
            "question_1": str,    – follow-up question to deepen engagement
            "question_2": str,    – secondary probing question
            "soft_close": str,    – appointment ask
        }
    """
    th = (treatment or "").lower()

    if "fail" in th and "ivf" in th:
        return {
            "opening": (
                "Hello, this is Parivar Saathi calling. I understand you've been through IVF before "
                "and it's been a difficult journey. I'm not here to pitch anything — "
                "I'd simply like to understand your situation better and see if we can help. "
                "Is this a good time?"
            ),
            "question_1": "Could you share a little about your previous IVF experience — which clinic, and what happened?",
            "question_2": "What has been the most challenging part of this journey for you?",
            "soft_close": (
                "Based on what you've shared, I'd like to arrange a detailed review with our specialist — "
                "completely at no cost. They can look at your previous reports and give you an honest "
                "second opinion. Would you be open to that?"
            ),
        }

    if "ivf" in th:
        return {
            "opening": (
                "Hello, this is Parivar Saathi calling. I can see you've had experience with IVF. "
                "I'd love to understand where you are in your journey right now. "
                "Is this a good time to talk briefly?"
            ),
            "question_1": "How did your previous IVF cycle go, and what are you considering next?",
            "question_2": "What's the most important thing you're looking for in a clinic at this point?",
            "soft_close": (
                "It sounds like the right next step would be a consultation with our specialist "
                "who can review your history and suggest a personalised approach. "
                "Could we set that up for you this week?"
            ),
        }

    if "iui" in th:
        return {
            "opening": (
                "Hello, this is Parivar Saathi calling. I understand you've tried IUI — "
                "that takes courage and patience. I wanted to share some information about "
                "what the next step could look like. Is this a good time?"
            ),
            "question_1": "How many IUI cycles have you done, and how did they go?",
            "question_2": "Have your doctors discussed IVF as a next option with you?",
            "soft_close": (
                "Many couples who've done IUI find a consultation with a fertility specialist very clarifying. "
                "It helps decide whether IVF is the right step or if there's more to explore. "
                "Would you like me to set up a free consultation?"
            ),
        }

    if lead_score == "Hot":
        return {
            "opening": (
                "Hello, this is Parivar Saathi calling. I know you reached out to us "
                "and I wanted to personally follow up. I can imagine this has been a long road. "
                "Do you have a few minutes to talk?"
            ),
            "question_1": "Can you tell me a bit about your fertility journey so far?",
            "question_2": "Have you spoken to a fertility specialist recently, or are you still at the evaluation stage?",
            "soft_close": (
                "Based on what you've shared, I'd suggest a consultation with our specialist — "
                "it's free and can give you a clear picture of your options. "
                "Would this week work for you?"
            ),
        }

    if lead_score == "Warm":
        return {
            "opening": (
                "Hello, this is Parivar Saathi calling. You reached out to us recently "
                "and I wanted to follow up personally. Hope this is a good time?"
            ),
            "question_1": "How long have you and your partner been trying, and how are you feeling about it?",
            "question_2": "Have you had any fertility tests done so far?",
            "soft_close": (
                "A simple fertility check-up can give you a lot of clarity at this stage — "
                "it's not a big commitment, just an information session. "
                "Would you be open to scheduling one?"
            ),
        }

    # Cold lead
    return {
        "opening": (
            "Hello, this is Parivar Saathi. You had reached out to us and I just wanted "
            "to check in briefly. Hope you're doing well?"
        ),
        "question_1": "How are things going? Are you still in the early stages of planning?",
        "question_2": "Is there anything you'd like to know about fertility and your options at this stage?",
        "soft_close": (
            "We offer a free information session with our fertility advisor — "
            "no pressure, just to answer your questions. Would that be useful?"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Objection detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_objection(caller_text: str) -> Optional[str]:
    """
    Scan caller speech for objection keywords.
    Returns the first matched objection type, or None.
    Priority: not_interested → cost → delay → fear → second_opinion → partner
    """
    text = caller_text.lower()

    priority_order = [
        OBJECTION_NOT_INTERESTED,
        OBJECTION_COST,
        OBJECTION_DELAY,
        OBJECTION_FEAR,
        OBJECTION_SECOND_OPINION,
        OBJECTION_PARTNER,
    ]
    for obj_type in priority_order:
        for kw in OBJECTION_KEYWORDS[obj_type]:
            if kw in text:
                return obj_type
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Objection handling
# ─────────────────────────────────────────────────────────────────────────────

def handle_objection(
    objection_type: str,
    lead_score: str = "Warm",
    prior_treatment: Optional[str] = None,
) -> dict:
    """
    Returns a structured objection response:
        {
            "acknowledge": str,    – empathetic validation
            "reframe":     str,    – reframe the concern
            "next_step":   str,    – concrete ask after handling objection
            "exit_if_repeated": bool  – True if this is the 2nd time objection raised
        }
    """
    th = (prior_treatment or "").lower()
    has_ivf_history = "ivf" in th

    handlers = {
        OBJECTION_COST: _handle_cost(lead_score, has_ivf_history),
        OBJECTION_DELAY: _handle_delay(lead_score),
        OBJECTION_FEAR: _handle_fear(has_ivf_history),
        OBJECTION_SECOND_OPINION: _handle_second_opinion(),
        OBJECTION_PARTNER: _handle_partner(),
        OBJECTION_NOT_INTERESTED: _handle_not_interested(),
    }
    return handlers.get(objection_type, _handle_default())


def _handle_cost(lead_score: str, has_ivf_history: bool) -> dict:
    acknowledge = "Completely understandable — IVF costs are significant and we take that seriously."
    reframe = (
        "We offer flexible payment plans and can help you understand what's covered. "
        "Importantly, we only recommend what's medically right for your case — "
        "no unnecessary procedures."
        if not has_ivf_history else
        "Having gone through this before, you know the cost is real. "
        "We want to make sure any investment is targeted and maximises your chances — "
        "which is why we do a thorough review before recommending anything."
    )
    next_step = (
        "Let's start with a free consultation — no commitment, no cost. "
        "After that, we can give you a clear cost estimate based on your specific situation."
    )
    return {"acknowledge": acknowledge, "reframe": reframe,
            "next_step": next_step, "exit_if_repeated": False}


def _handle_delay(lead_score: str) -> dict:
    acknowledge = "I respect that — you know your situation best."
    reframe = (
        "I just want to share one thought: fertility is time-sensitive, "
        "and the information from a consultation costs nothing but can change how you plan. "
        "It's not about rushing into treatment — it's about knowing your options."
        if lead_score in ("Hot", "Warm") else
        "That makes complete sense at this early stage. "
        "Many couples prefer to try naturally for a while longer — that's completely valid."
    )
    next_step = (
        "Would you be open to just a brief information call — 15 minutes, no obligation? "
        "You can decide about treatment entirely at your own pace."
        if lead_score in ("Hot", "Warm") else
        "If things don't progress in the next few months, please do reach out. "
        "We're here whenever you're ready."
    )
    return {"acknowledge": acknowledge, "reframe": reframe,
            "next_step": next_step, "exit_if_repeated": lead_score == "Cold"}


def _handle_fear(has_ivf_history: bool) -> dict:
    acknowledge = "That fear is completely natural — and I want you to know it's safe to feel that way."
    reframe = (
        "What you went through was hard, and it makes sense that you're cautious. "
        "We would start by understanding exactly what happened in your previous cycle "
        "before suggesting anything new. You deserve answers, not just another attempt."
        if has_ivf_history else
        "Most of our patients felt the same before their first consultation. "
        "What helps is having clear information — then the unknown feels less scary. "
        "There is no pressure to make any decision at a consultation."
    )
    next_step = (
        "Can we arrange a conversation with our specialist? "
        "No commitment — just a space to ask questions and understand your options."
    )
    return {"acknowledge": acknowledge, "reframe": reframe,
            "next_step": next_step, "exit_if_repeated": False}


def _handle_second_opinion() -> dict:
    acknowledge = "That is a very sensible approach — getting a second opinion is a sign of a well-informed patient."
    reframe = (
        "We welcome that completely. We are happy to review your existing reports "
        "and give you an honest assessment — even if the conclusion is that your current "
        "clinic is the right fit for you."
    )
    next_step = (
        "Could we set up a report review session with our specialist? "
        "It's free and you'll walk away with a clear, independent view."
    )
    return {"acknowledge": acknowledge, "reframe": reframe,
            "next_step": next_step, "exit_if_repeated": False}


def _handle_partner() -> dict:
    acknowledge = "Absolutely — this is a decision you should make together."
    reframe = (
        "I completely understand. Fertility treatment works best when both partners "
        "are aligned. Would it be possible for both of you to join a call together? "
        "We can walk through everything and answer all questions at once."
    )
    next_step = (
        "If a joint call isn't possible right now, I can send you a short summary "
        "that covers everything we discussed — easy to share with your partner. "
        "Would that help?"
    )
    return {"acknowledge": acknowledge, "reframe": reframe,
            "next_step": next_step, "exit_if_repeated": False}


def _handle_not_interested() -> dict:
    acknowledge = "Of course — I completely respect that."
    reframe = "We won't call again unless you reach out to us."
    next_step = (
        "If your situation changes, our WhatsApp is always available — "
        "day or night, no pressure. Take care and I wish you all the best."
    )
    return {"acknowledge": acknowledge, "reframe": reframe,
            "next_step": next_step, "exit_if_repeated": True}


def _handle_default() -> dict:
    return {
        "acknowledge": "I understand.",
        "reframe": "Let me make sure I address that properly.",
        "next_step": "Could you tell me a little more so I can help better?",
        "exit_if_repeated": False,
    }
