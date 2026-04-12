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
    All scripts are in natural Hindi for Sarvam TTS.

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
                "नमस्ते, मैं परिवार साथी से बोल रही हूँ। "
                "मुझे पता है कि आपने पहले आई वी एफ़ करवाया है और ये सफ़र आसान नहीं रहा। "
                "मैं कोई बिक्री की बात करने नहीं आई हूँ। बस आपकी स्थिति समझना चाहती हूँ। "
                "क्या अभी आपके पास दो मिनट हैं?"
            ),
            "question_1": "आप बताइए, पिछली बार आई वी एफ़ कहाँ करवाया था और कैसा अनुभव रहा?",
            "question_2": "इस पूरे सफ़र में सबसे मुश्किल क्या लगा आपको?",
            "soft_close": (
                "आपने जो बताया उसके हिसाब से, हमारे डॉक्टर आपकी पुरानी रिपोर्ट्स देखकर "
                "एक ईमानदार राय दे सकते हैं। ये बिल्कुल मुफ़्त है। "
                "क्या आप इसके लिए तैयार होंगी?"
            ),
        }

    if "ivf" in th:
        return {
            "opening": (
                "नमस्ते, मैं परिवार साथी से बोल रही हूँ। "
                "मुझे पता है कि आपने आई वी एफ़ का अनुभव किया है। "
                "मैं जानना चाहती हूँ कि अभी आप कहाँ हैं इस सफ़र में। "
                "क्या दो मिनट बात कर सकते हैं?"
            ),
            "question_1": "आपका पिछला आई वी एफ़ साइकल कैसा रहा, और अब आगे क्या सोच रहे हैं?",
            "question_2": "अभी क्लिनिक चुनने में आपके लिए सबसे ज़रूरी बात क्या है?",
            "soft_close": (
                "लगता है कि अगला सही कदम हमारे डॉक्टर से बात करना होगा। "
                "वो आपकी पूरी हिस्ट्री देखकर सही सलाह दे सकते हैं। "
                "क्या इस हफ़्ते टाइम निकाल पाएंगे?"
            ),
        }

    if "iui" in th:
        return {
            "opening": (
                "नमस्ते, मैं परिवार साथी से बोल रही हूँ। "
                "मुझे पता है कि आपने आई यू आई ट्राई किया है। "
                "ये हिम्मत और धीरज की बात है। "
                "मैं आपको आगे के विकल्पों के बारे में बताना चाहती हूँ। क्या अभी ठीक है?"
            ),
            "question_1": "आपने कितने आई यू आई साइकल किए और कैसा रहा?",
            "question_2": "क्या आपके डॉक्टर ने आई वी एफ़ के बारे में बात की है?",
            "soft_close": (
                "एक बार हमारे फर्टिलिटी डॉक्टर से बात करने से बहुत कुछ साफ़ हो जाता है। "
                "ये बिल्कुल मुफ़्त है और कोई दबाव नहीं है। "
                "क्या मैं एक कंसल्टेशन बुक कर दूँ?"
            ),
        }

    if lead_score == "Hot":
        return {
            "opening": (
                "नमस्ते, मैं परिवार साथी से बोल रही हूँ। "
                "आपने हमसे संपर्क किया था, तो मैं खुद फ़ॉलो अप कर रही हूँ। "
                "मैं समझ सकती हूँ कि ये एक लंबा सफ़र रहा है। "
                "क्या दो मिनट बात कर सकते हैं?"
            ),
            "question_1": "ज़रा बताइए, अभी तक आपका फर्टिलिटी का सफ़र कैसा रहा है?",
            "question_2": "क्या हाल ही में किसी फर्टिलिटी डॉक्टर से मिले हैं, या अभी जानकारी इकट्ठा कर रहे हैं?",
            "soft_close": (
                "आपने जो बताया उससे लगता है कि हमारे डॉक्टर से एक बार बात करना फ़ायदेमंद होगा। "
                "ये मुफ़्त है और आपको अपने सभी विकल्प साफ़ हो जाएंगे। "
                "क्या इस हफ़्ते कोई टाइम सूट करेगा?"
            ),
        }

    if lead_score == "Warm":
        return {
            "opening": (
                "नमस्ते, मैं परिवार साथी से बोल रही हूँ। "
                "आपने हाल ही में हमसे संपर्क किया था, तो मैं फ़ॉलो अप कर रही हूँ। "
                "उम्मीद है अभी बात करने का अच्छा समय है?"
            ),
            "question_1": "आप और आपके पार्टनर कितने समय से कोशिश कर रहे हैं, और कैसा महसूस हो रहा है?",
            "question_2": "क्या अभी तक कोई फर्टिलिटी टेस्ट करवाए हैं?",
            "soft_close": (
                "एक सिंपल फर्टिलिटी चेकअप से बहुत कुछ पता चल जाता है। "
                "कोई बड़ी बात नहीं है, बस जानकारी के लिए। "
                "क्या आप एक अपॉइंटमेंट लेना चाहेंगे?"
            ),
        }

    # Cold lead
    return {
        "opening": (
            "नमस्ते, मैं परिवार साथी से बोल रही हूँ। "
            "आपने हमसे संपर्क किया था, बस हाल-चाल जानना चाहती थी। "
            "उम्मीद है सब ठीक है?"
        ),
        "question_1": "कैसा चल रहा है? क्या अभी शुरुआती दौर में हैं प्लानिंग की?",
        "question_2": "क्या फर्टिलिटी और अपने विकल्पों के बारे में कुछ जानना चाहेंगे?",
        "soft_close": (
            "हम एक मुफ़्त जानकारी सत्र देते हैं फर्टिलिटी एडवाइज़र के साथ। "
            "कोई दबाव नहीं, बस आपके सवालों के जवाब। "
            "क्या ये आपके काम आएगा?"
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
    acknowledge = "बिल्कुल सही कहा आपने। आई वी एफ़ का खर्चा काफ़ी होता है, ये हम अच्छे से समझते हैं।"
    reframe = (
        "हम आसान किस्तों की सुविधा देते हैं। "
        "और सबसे ज़रूरी बात, हम सिर्फ़ वही सलाह देते हैं जो मेडिकली सही हो। "
        "कोई बेवजह का ख़र्चा नहीं।"
        if not has_ivf_history else
        "आपने पहले भी ये सफ़र तय किया है तो आपको पता है कि ख़र्चा कितना होता है। "
        "हम चाहते हैं कि आपका हर पैसा सही जगह लगे। "
        "इसलिए हम पहले पूरी तरह रिव्यू करते हैं।"
    )
    next_step = (
        "चलिए पहले एक मुफ़्त कंसल्टेशन से शुरू करते हैं। कोई ख़र्चा नहीं, कोई दबाव नहीं। "
        "उसके बाद हम आपकी स्थिति के हिसाब से सही अनुमान बता सकते हैं।"
    )
    return {"acknowledge": acknowledge, "reframe": reframe,
            "next_step": next_step, "exit_if_repeated": False}


def _handle_delay(lead_score: str) -> dict:
    acknowledge = "मैं आपकी बात समझती हूँ। आप अपनी स्थिति सबसे अच्छे से जानते हैं।"
    reframe = (
        "बस एक बात कहना चाहूँगी कि फर्टिलिटी में समय बहुत मायने रखता है। "
        "एक कंसल्टेशन में कोई ख़र्चा नहीं लगता, लेकिन जो जानकारी मिलती है वो बहुत काम की होती है। "
        "ये इलाज की जल्दी नहीं है, बस अपने विकल्प जानने की बात है।"
        if lead_score in ("Hot", "Warm") else
        "ये बिल्कुल सही सोच है इस शुरुआती दौर में। "
        "बहुत से जोड़े कुछ और समय नेचुरली ट्राई करना चाहते हैं और ये पूरी तरह सही है।"
    )
    next_step = (
        "क्या आप बस पंद्रह मिनट की एक जानकारी वाली कॉल के लिए तैयार होंगे? "
        "कोई बंधन नहीं। इलाज का फ़ैसला पूरी तरह आपके हाथ में रहेगा।"
        if lead_score in ("Hot", "Warm") else
        "अगर अगले कुछ महीनों में बात नहीं बनती, तो ज़रूर संपर्क कीजिएगा। "
        "हम यहाँ हैं जब भी आप तैयार हों।"
    )
    return {"acknowledge": acknowledge, "reframe": reframe,
            "next_step": next_step, "exit_if_repeated": lead_score == "Cold"}


def _handle_fear(has_ivf_history: bool) -> dict:
    acknowledge = "ये डर बिल्कुल स्वाभाविक है। और मैं चाहती हूँ कि आप जानें कि ऐसा महसूस करना ठीक है।"
    reframe = (
        "आपने जो पहले झेला है वो आसान नहीं था। सतर्क रहना समझदारी है। "
        "हम पहले ये समझेंगे कि पिछली बार क्या हुआ था, "
        "उसके बाद ही कुछ नया सुझाएंगे। आपको जवाब मिलने चाहिए, बस एक और कोशिश नहीं।"
        if has_ivf_history else
        "हमारे ज़्यादातर मरीज़ पहली कंसल्टेशन से पहले ऐसा ही महसूस करते थे। "
        "सही जानकारी मिलने पर अनजान डर कम हो जाता है। "
        "कंसल्टेशन में कोई फ़ैसला लेने का दबाव नहीं होता।"
    )
    next_step = (
        "क्या हम डॉक्टर से एक बात करवा दें? "
        "कोई बंधन नहीं, बस सवाल पूछने और विकल्प समझने का मौका।"
    )
    return {"acknowledge": acknowledge, "reframe": reframe,
            "next_step": next_step, "exit_if_repeated": False}


def _handle_second_opinion() -> dict:
    acknowledge = "ये बहुत समझदारी भरा कदम है। दूसरी राय लेना एक जागरूक मरीज़ की निशानी है।"
    reframe = (
        "हम इसका पूरा स्वागत करते हैं। हम ख़ुशी से आपकी मौजूदा रिपोर्ट्स देखकर "
        "ईमानदार राय देंगे। अगर नतीजा ये भी हो कि आपकी मौजूदा क्लिनिक सही है, "
        "तो भी हम वही बताएंगे।"
    )
    next_step = (
        "क्या हम डॉक्टर के साथ एक रिपोर्ट रिव्यू सेशन रख दें? "
        "ये मुफ़्त है और आपको एक स्वतंत्र राय मिल जाएगी।"
    )
    return {"acknowledge": acknowledge, "reframe": reframe,
            "next_step": next_step, "exit_if_repeated": False}


def _handle_partner() -> dict:
    acknowledge = "बिल्कुल सही। ये फ़ैसला दोनों को मिलकर लेना चाहिए।"
    reframe = (
        "मैं पूरी तरह समझती हूँ। फर्टिलिटी ट्रीटमेंट तब सबसे अच्छा काम करता है "
        "जब दोनों पार्टनर एक साथ हों। क्या दोनों मिलकर एक कॉल जॉइन कर सकते हैं? "
        "हम सब कुछ समझा देंगे और सारे सवालों के जवाब दे देंगे।"
    )
    next_step = (
        "अगर अभी जॉइंट कॉल मुश्किल है, तो मैं आपको एक छोटा सा सारांश भेज सकती हूँ "
        "जो आप अपने पार्टनर के साथ शेयर कर सकते हैं। क्या ये ठीक रहेगा?"
    )
    return {"acknowledge": acknowledge, "reframe": reframe,
            "next_step": next_step, "exit_if_repeated": False}


def _handle_not_interested() -> dict:
    acknowledge = "जी बिल्कुल, मैं आपकी बात का पूरा सम्मान करती हूँ।"
    reframe = "जब तक आप ख़ुद संपर्क नहीं करेंगे, हम दोबारा कॉल नहीं करेंगे।"
    next_step = (
        "अगर कभी मन बदले, तो हमारा वॉट्सऐप हमेशा उपलब्ध है। "
        "दिन हो या रात, कोई दबाव नहीं। अपना ख़्याल रखिए।"
    )
    return {"acknowledge": acknowledge, "reframe": reframe,
            "next_step": next_step, "exit_if_repeated": True}


def _handle_default() -> dict:
    return {
        "acknowledge": "जी, मैं समझ सकती हूँ।",
        "reframe": "मैं आपकी बात को सही से समझना चाहती हूँ।",
        "next_step": "क्या आप थोड़ा और बता सकते हैं ताकि मैं बेहतर मदद कर सकूँ?",
        "exit_if_repeated": False,
    }
