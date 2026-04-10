from database import save_lead

class IVFConversationEngine:
    def __init__(self, client, session_id=None):
        self.client = client
        self.session_id = session_id

        self.state = "Q1"
        self.data = {}
        self.lead_score = 0

    def process_turn(self, user_input: str):
        user_input = user_input.strip()
        user_lower = user_input.lower()

        # ── Q1: Duration ─────────────────────────
        if self.state == "Q1":

            # If only number → ask clarification
            if user_input.isdigit():
                self.state = "Q1_CLARIFY"
                self.data["duration_raw"] = user_input

                return {
                    "response_text": "Just to confirm — is that months or years?",
                    "action": None,
                    "lead_score": self.lead_score
                }

            self.data["duration"] = user_input
            self.state = "Q2"

            return {
                "response_text": "Got it.\n\nWhat is your age?",
                "action": None,
                "lead_score": self.lead_score
            }

        # ── Q1 CLARIFY ──────────────────────────
        elif self.state == "Q1_CLARIFY":
            self.data["duration"] = self.data["duration_raw"] + " " + user_input
            self.state = "Q2"

            return {
                "response_text": "Got it.\n\nWhat is your age?",
                "action": None,
                "lead_score": self.lead_score
            }

        # ── Q2: Age ──────────────────────────────
        elif self.state == "Q2":
            self.data["age"] = user_input
            self.state = "Q3"

            return {
                "response_text": "Have you taken any fertility treatment before? (Yes/No)",
                "action": None,
                "lead_score": self.lead_score
            }

        # ── Q3: Treatment ────────────────────────
        elif self.state == "Q3":
            self.data["treatment"] = user_input
            self.state = "ASK_CONNECT"

            return {
                "response_text":
                    "I think it would really help to speak with our counsellor.\n\n"
                    "They can guide you based on your situation.\n\n"
                    "Should I connect you?",
                "action": "offer_counsellor",
                "lead_score": self.lead_score
            }

        # ── ASK CONNECT ──────────────────────────
        elif self.state == "ASK_CONNECT":
            if user_lower in ["yes", "haan", "yes please", "ok", "okay"]:
                self.state = "ASK_NAME"
                return {
                    "response_text": "Great 😊\n\nMay I have your name?",
                    "action": "capture_name",
                    "lead_score": self.lead_score
                }
            else:
                return {
                    "response_text":
                        "No problem at all.\n\nIf you change your mind, I’m here to help.",
                    "action": None,
                    "lead_score": self.lead_score
                }

        # ── ASK NAME ─────────────────────────────
        elif self.state == "ASK_NAME":
            self.data["name"] = user_input
            self.state = "ASK_PHONE"

            return {
                "response_text":
                    f"Thanks {user_input}.\n\nPlease share your phone number so our counsellor can reach you.",
                "action": "capture_phone",
                "lead_score": self.lead_score
            }

        # ── ASK PHONE ────────────────────────────
        elif self.state == "ASK_PHONE":
            self.data["phone"] = user_input
            self.state = "DONE"

            # ✅ SAVE LEAD TO DATABASE
            try:
                save_lead({
                    "name": self.data.get("name"),
                    "phone": self.data.get("phone"),
                    "duration": self.data.get("duration"),
                    "age": self.data.get("age"),
                    "treatment": self.data.get("treatment"),
                    "session_id": self.session_id
                })
            except Exception as e:
                print("DB ERROR:", str(e))

            return {
                "response_text":
                    "You're all set ✅\n\n"
                    "Our counsellor will reach out to you shortly.",
                "action": "lead_captured",
                "lead_score": self.lead_score
            }

        # ── DONE ────────────────────────────────
        else:
            return {
                "response_text": "Our team will connect with you shortly. 😊",
                "action": None,
                "lead_score": self.lead_score
            }