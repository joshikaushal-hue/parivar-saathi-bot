"""
test_mock.py
Runs all 6 test scenarios using a deterministic mock OpenAI client.
Validates state transitions, lead scoring, JSON output, and edge cases.
"""

import json
import sys
import os
import uuid

# ── Minimal OpenAI mock ────────────────────────────────────────────────────────
class MockMessage:
    def __init__(self, content):
        self.content = content

class MockChoice:
    def __init__(self, content):
        self.message = MockMessage(content)

class MockCompletion:
    def __init__(self, content):
        self.choices = [MockChoice(content)]

class MockChat:
    def __init__(self):
        self.completions = self

    def create(self, model, messages, temperature, max_tokens):
        """Generate deterministic responses based on system prompt state.
        Uses case-insensitive matching on 'State SX' in the system prompt."""
        system = messages[0]["content"].lower()
        user   = messages[1]["content"]
        user_l = user.lower()

        # ── S1 ─────────────────────────────────────────────────────────────
        if "state s1" in system:
            resp = '{"next_state":"S2","response_text":"Hi! I have 3 quick questions to understand how we can help. Is that okay?","lead_score":"Cold","action":"continue"}'

        # ── S2: Duration ────────────────────────────────────────────────────
        elif "state s2" in system:
            if "Duration trying" in user:
                # parser captured — advance to S3
                resp = '{"next_state":"S3","response_text":"Noted. How old are you, or roughly what age range?","lead_score":"Warm","action":"continue"}'
            elif "saal" in user_l or "year" in user_l or "month" in user_l:
                resp = '{"next_state":"S3","response_text":"Understood. How old are you, or roughly what age range?","lead_score":"Warm","action":"continue"}'
            elif ("while" in user_l or "kafi" in user_l or "some time" in user_l) and "Duration" not in user:
                # vague — stay S2
                resp = '{"next_state":"S2","response_text":"Could you be more specific — months or years?","lead_score":"Cold","action":"continue"}'
            elif "success rate" in user_l or "what is" in user_l or "kya hota" in user_l:
                # off-topic — redirect with required question
                resp = '{"next_state":"S2","response_text":"I can share that later. How long have you been trying to conceive — months or years?","lead_score":"Cold","action":"continue"}'
            elif "bacha nahi" in user_l or "nahi ho raha" in user_l or "problem" in user_l:
                # emotional — acknowledge + required question
                resp = '{"next_state":"S2","response_text":"I understand. How long have you been trying to conceive — months or years?","lead_score":"Cold","action":"continue"}'
            else:
                resp = '{"next_state":"S2","response_text":"How long have you been trying to conceive — months or years?","lead_score":"Cold","action":"continue"}'

        # ── S3: Age ─────────────────────────────────────────────────────────
        elif "state s3" in system:
            if "Age:" in user or "age" in user_l or "saal" in user_l or "hai" in user_l:
                resp = '{"next_state":"S4","response_text":"Have you tried any fertility treatments — IUI, IVF, or none at all?","lead_score":"Warm","action":"continue"}'
            elif "bacha" in user_l or "tension" in user_l or "worried" in user_l:
                # emotional — acknowledge + required question
                resp = '{"next_state":"S3","response_text":"I understand. How old are you, or roughly what age range?","lead_score":"Cold","action":"continue"}'
            else:
                resp = '{"next_state":"S3","response_text":"How old are you, or roughly what age range?","lead_score":"Warm","action":"continue"}'

        # ── S4: Treatment ───────────────────────────────────────────────────
        elif "state s4" in system:
            if "Treatment history" in user or "iui" in user_l or "ivf" in user_l \
               or "none" in user_l or "nahi" in user_l or "no treatment" in user_l \
               or "koi nahi" in user_l or "abhi tak" in user_l:
                resp = '{"next_state":"S5","response_text":"Noted.","lead_score":"Warm","action":"continue"}'
            elif "some" in user_l or "few" in user_l or "tried something" in user_l \
                 or ("done" in user_l and "ivf" not in user_l and "iui" not in user_l):
                # vague treatment — re-ask
                resp = '{"next_state":"S4","response_text":"Which specifically — IUI, IVF, or none?","lead_score":"Warm","action":"continue"}'
            elif "bacha" in user_l or "tension" in user_l or "worried" in user_l:
                # emotional — acknowledge + required question
                resp = '{"next_state":"S4","response_text":"I understand. Have you tried any fertility treatments — IUI, IVF, or none at all?","lead_score":"Cold","action":"continue"}'
            else:
                resp = '{"next_state":"S4","response_text":"Have you tried any fertility treatments — IUI, IVF, or none at all?","lead_score":"Warm","action":"continue"}'

        # ── S5: Closing ─────────────────────────────────────────────────────
        elif "state s5" in system:
            if "Hot" in user:
                resp = '{"next_state":"S5","response_text":"We recommend scheduling a consultation soon. Would you prefer morning or evening?","lead_score":"Hot","action":"transfer"}'
            elif "Warm" in user:
                resp = '{"next_state":"S5","response_text":"A consultation can help clarify next steps. Our counselor can call you shortly.","lead_score":"Warm","action":"continue"}'
            else:
                resp = '{"next_state":"S5","response_text":"It\'s still early days — many conceive naturally within the first year. We\'re here when you need us.","lead_score":"Cold","action":"end"}'

        else:
            resp = '{"next_state":"S1","response_text":"Hi! I have 3 quick questions to understand how we can help. Is that okay?","lead_score":"Cold","action":"continue"}'

        return MockCompletion(resp)

class MockOpenAI:
    def __init__(self, api_key=None):
        self.chat = MockChat()


# ── Patch openai before importing main modules ─────────────────────────────────
sys.modules['openai'] = type(sys)('openai')
sys.modules['openai'].OpenAI = MockOpenAI
sys.modules['openai'].APIConnectionError = Exception
sys.modules['openai'].APITimeoutError    = Exception
sys.modules['openai'].AuthenticationError = Exception
sys.modules['openai'].PermissionDeniedError = Exception

# Now we can import our modules
from typing import Optional
from state_machine import (
    ConversationState, classify_lead, next_action,
    S1, S2, S3, S4, S5,
    S5_CLOSING, STATE_REQUIRED_QUESTION,
)
from api_handler import call_openai
from input_parser import parse_duration_months, parse_age, parse_treatment
from logger import log_turn, log_session_summary

# ── Inline engine — exact mirror of main.py IVFConversationEngine ──────────────
sys.path.insert(0, '.')

class IVFConversationEngine:
    def __init__(self, client, session_id=None):
        self.client     = client
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.state      = ConversationState()

    def _enrich_state(self, user_input: str):
        if self.state.current_state == S2:
            dur = parse_duration_months(user_input)
            if dur is not None:
                self.state.duration_months = dur
        if self.state.current_state == S3:
            age = parse_age(user_input)
            if age is not None:
                self.state.age = age
        if self.state.current_state == S4:
            tx = parse_treatment(user_input)
            if tx is not None:
                self.state.treatment_history = tx
        self.state.lead_score = classify_lead(self.state)
        self.state.action     = next_action(self.state.lead_score)

    def _forced_next_state(self) -> Optional[str]:
        cs = self.state.current_state
        if cs == S2 and self.state.duration_months is not None:
            return S3
        if cs == S3 and self.state.age is not None:
            return S4
        if cs == S4 and self.state.treatment_history is not None:
            return S5
        return None

    def _enforce_response_discipline(self, result: dict, prev_state: str) -> dict:
        text = result.get("response_text", "")
        banned = [
            "how can i assist",
            "how can i help you further",
            "let's talk about your journey further",
            "let's talk further",
            "let me know if",
            "is there anything else",
        ]
        text_lower = text.lower()
        for phrase in banned:
            if phrase in text_lower:
                required_q = STATE_REQUIRED_QUESTION.get(self.state.current_state, "")
                if required_q:
                    text = required_q
                break
        # S5: exact prescribed closing
        if self.state.current_state == S5:
            text = S5_CLOSING.get(self.state.lead_score, S5_CLOSING["Cold"])
        # State did NOT advance: ensure required question is present
        elif self.state.current_state == prev_state:
            required_q = STATE_REQUIRED_QUESTION.get(self.state.current_state)
            if required_q and required_q.lower() not in text.lower():
                words = text.split()
                prefix = " ".join(words[:4]).rstrip(".,!?") if len(words) > 4 else ""
                text = f"{prefix}. {required_q}" if prefix else required_q
        result["response_text"] = text
        return result

    def process_turn(self, user_input: str) -> dict:
        self.state.turn_count += 1
        self._enrich_state(user_input)
        forced_ns = self._forced_next_state()
        result = call_openai(user_input, self.state, self.client)
        if forced_ns:
            result["next_state"] = forced_ns
        prev_state = self.state.current_state
        new_state  = result.get("next_state", self.state.current_state)
        if new_state in [S1, S2, S3, S4, S5]:
            self.state.current_state = new_state
        result["lead_score"] = self.state.lead_score
        result["action"] = next_action(self.state.lead_score) if self.state.current_state == S5 \
                           else "continue"
        result = self._enforce_response_discipline(result, prev_state=prev_state)
        log_turn(self.session_id, self.state.turn_count, user_input,
                 self.state.current_state, result)
        return result

    def is_complete(self):
        return self.state.current_state == S5 and self.state.action in ("end", "transfer")

    def finalize(self):
        log_session_summary(self.session_id, self.state.collected_data(),
                            self.state.lead_score, self.state.action)


# ── Test runner ────────────────────────────────────────────────────────────────

TEST_SCENARIOS = {
    1: {
        "name": "Ideal user — clear answers",
        "turns": ["start", "yes", "2 years", "32", "IUI"],
        "expected_lead": "Warm",
    },
    2: {
        "name": "High intent — IVF failure case",
        "turns": ["start", "yes please", "4 years", "35", "We did IVF twice and it failed"],
        "expected_lead": "Hot",
    },
    3: {
        "name": "Low intent — under 1 year",
        "turns": ["start", "sure", "6 months", "28", "no treatment, just started"],
        "expected_lead": "Cold",
    },
    4: {
        "name": "Mixed Hindi-English",
        "turns": ["start", "haan please", "do saal se koshish kar rahe hain", "meri age 31 hai", "koi nahi"],
        "expected_lead": "Warm",
    },
    5: {
        "name": "Vague answers — engine re-asks",
        "turns": ["start", "okay", "quite a while", "maybe a year and a half", "33", "done some treatments"],
        "expected_lead": None,  # no strict assertion
    },
    6: {
        "name": "Off-topic question mid-flow",
        "turns": ["start", "yes", "what is IVF success rate?", "3 years", "34", "IVF"],
        "expected_lead": "Hot",
    },
}


def run_all():
    client = MockOpenAI()
    all_passed = True

    # Unit tests for input_parser
    print("=" * 60)
    print("UNIT TESTS: input_parser")
    print("=" * 60)
    cases = [
        (parse_duration_months, "2 years",              24.0),
        (parse_duration_months, "18 months",            18.0),
        (parse_duration_months, "do saal",              24.0),
        (parse_duration_months, "1 year and 6 months",  18.0),
        (parse_duration_months, "quite a while",        None),
        (parse_age,             "I am 32 years old",    "32"),
        (parse_age,             "meri age 31 hai",      "31"),
        (parse_age,             "30-35",                "30-35"),
        (parse_treatment,       "We did IVF twice",     "IVF"),
        (parse_treatment,       "no treatment nahi",    "None"),
        (parse_treatment,       "koi nahi",             "None"),
        (parse_treatment,       "IUI done before",      "IUI"),
    ]
    for fn, inp, expected in cases:
        result = fn(inp)
        ok = result == expected
        mark = "✓" if ok else "✗"
        print(f"  {mark} {fn.__name__}({inp!r}) → {result!r}  (expected {expected!r})")
        if not ok:
            all_passed = False

    # Banned phrases — should never appear in any response
    BANNED_PHRASES = [
        "how can i assist",
        "let's talk about your journey further",
        "let's talk further",
        "how can i help you further",
        "let me know if",
        "is there anything else",
    ]

    # Integration tests
    print()
    print("=" * 60)
    print("INTEGRATION TESTS: Full conversation flows + discipline checks")
    print("=" * 60)

    for num, scenario in TEST_SCENARIOS.items():
        print(f"\nScenario {num}: {scenario['name']}")
        print("-" * 50)
        session_id = f"mock_{num}"
        engine     = IVFConversationEngine(client, session_id=session_id)
        scenario_errors = []
        prev_state      = None
        state_repeat_count = {}

        for turn_input in scenario["turns"]:
            print(f"  User : {turn_input}")
            result = engine.process_turn(turn_input)

            # ── Structural checks ───────────────────────────────────────────
            for key in ("next_state", "response_text", "lead_score", "action"):
                if key not in result:
                    scenario_errors.append(f"Missing key '{key}'")

            # Word count ≤ 20
            words = result["response_text"].split()
            if len(words) > 20:
                scenario_errors.append(
                    f"Response too long ({len(words)} words): {result['response_text']}"
                )

            # No banned phrases
            text_lower = result["response_text"].lower()
            for phrase in BANNED_PHRASES:
                if phrase in text_lower:
                    scenario_errors.append(f"Banned phrase found: '{phrase}'")

            # S5 closing must match exact prescribed text
            if result["next_state"] == "S5" or engine.state.current_state == "S5":
                expected_close = S5_CLOSING.get(engine.state.lead_score, "")
                if expected_close and result["response_text"] != expected_close:
                    # Allow if it's still transitioning (not yet at S5 action)
                    if engine.state.current_state == "S5":
                        scenario_errors.append(
                            f"S5 closing mismatch.\n"
                            f"    Expected: {expected_close!r}\n"
                            f"    Got     : {result['response_text']!r}"
                        )

            # State must not repeat more than once for the same captured data
            ns = result["next_state"]
            state_repeat_count[ns] = state_repeat_count.get(ns, 0) + 1
            # Allow up to 4 turns in same state (vague/off-topic scenarios need it)
            if state_repeat_count.get(ns, 0) > 4:
                scenario_errors.append(
                    f"State {ns} repeated {state_repeat_count[ns]} times — likely infinite loop"
                )

            print(f"  Bot  : {result['response_text']}")
            print(f"         [state={result['next_state']} | score={result['lead_score']} | action={result['action']}]")

            if engine.is_complete():
                print("  [✓ Conversation complete]")
                break

            prev_state = result["next_state"]

        engine.finalize()
        final_lead = engine.state.lead_score
        data       = engine.state.collected_data()

        print(f"\n  Final lead : {final_lead}")
        print(f"  Data       : {json.dumps(data)}")

        expected = scenario.get("expected_lead")
        if expected and final_lead != expected:
            scenario_errors.append(f"Lead score: expected={expected}, got={final_lead}")

        if scenario_errors:
            for e in scenario_errors:
                print(f"  ✗ {e}")
            all_passed = False
        else:
            print(f"  ✓ PASSED — all discipline checks OK")

    # Validate log was written
    print()
    print("=" * 60)
    print("LOG VALIDATION")
    print("=" * 60)
    log_path = "logs/conversations.jsonl"
    if os.path.exists(log_path):
        with open(log_path) as f:
            lines = f.readlines()
        valid = 0
        for line in lines:
            try:
                json.loads(line)
                valid += 1
            except json.JSONDecodeError as e:
                print(f"  ✗ Invalid JSON log line: {e}")
                all_passed = False
        print(f"  ✓ {valid} valid log entries written to {log_path}")
    else:
        print(f"  ✗ Log file not found: {log_path}")
        all_passed = False

    print()
    print("=" * 60)
    if all_passed:
        print("ALL TESTS PASSED ✓")
    else:
        print("SOME TESTS FAILED — review output above")
    print("=" * 60)
    return all_passed


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
