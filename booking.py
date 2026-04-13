"""
booking.py
Phase 3 — In-Call Appointment Booking Engine

Provides:
  - Priority-based smart slot allocation
  - Booking creation + DB persistence
  - WhatsApp confirmation via Twilio
  - Slot availability management

Slot Strategy (IVF-specific):
  HIGH priority (age≥35 / trying≥2yr / failed IVF) → earliest slots (tomorrow)
  MEDIUM priority (moderate case)                   → next 2–3 days
  LOW priority (early stage)                        → flexible later slots

Clinic Hours: Mon–Sat, slots at 11:00 AM and 3:00 PM
"""

import os
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("ivf_engine")

DB_PATH = "leads.db"

# ── Clinic Configuration ────────────────────────────────────────────────────

CLINIC_SLOTS = ["11:00", "15:00"]         # 11 AM and 3 PM daily
CLINIC_DAYS = {0, 1, 2, 3, 4, 5}         # Mon=0 through Sat=5 (no Sunday)
MAX_BOOKINGS_PER_SLOT = 3                 # max patients per slot


# ── Priority Calculation ────────────────────────────────────────────────────

def calculate_lead_priority(
    age: Optional[str] = None,
    duration_months: Optional[float] = None,
    treatment_history: Optional[str] = None,
) -> str:
    """
    Determine lead priority based on clinical urgency signals.

    Returns: "high", "medium", or "low"

    Rules:
      HIGH  → age ≥ 35  OR  trying ≥ 24 months  OR  failed IVF
      MEDIUM → age ≥ 30  OR  trying ≥ 12 months  OR  any treatment attempted
      LOW   → everything else
    """
    priority = "low"

    # ── Parse age ──────────────────────────────────────────────────────────
    parsed_age = _parse_age(age)

    # ── Parse duration ─────────────────────────────────────────────────────
    parsed_duration = duration_months or 0

    # ── Parse treatment ────────────────────────────────────────────────────
    th = (treatment_history or "").lower()
    has_ivf = "ivf" in th
    has_failed_ivf = has_ivf and any(w in th for w in ["fail", "unsuccessful", "nahi hua", "nhi hua"])
    has_any_treatment = has_ivf or "iui" in th or "treatment" in th

    # ── HIGH priority ──────────────────────────────────────────────────────
    if parsed_age >= 35:
        priority = "high"
    elif parsed_duration >= 24:
        priority = "high"
    elif has_failed_ivf:
        priority = "high"
    # ── MEDIUM priority ────────────────────────────────────────────────────
    elif parsed_age >= 30:
        priority = "medium"
    elif parsed_duration >= 12:
        priority = "medium"
    elif has_any_treatment:
        priority = "medium"

    log.info(
        f"PRIORITY | age={parsed_age} | dur={parsed_duration}mo | "
        f"treatment={th!r} | → {priority}"
    )
    return priority


def _parse_age(age_str: Optional[str]) -> int:
    """Extract numeric age from various formats."""
    if not age_str:
        return 0
    import re
    # Find first number in the string
    match = re.search(r"(\d+)", str(age_str))
    return int(match.group(1)) if match else 0


# ── Smart Slot Allocation ───────────────────────────────────────────────────

def get_slots(priority: str) -> list:
    """
    Return available slots based on lead priority.

    HIGH   → tomorrow's slots (earliest available)
    MEDIUM → next 2–3 day slots
    LOW    → next 3–5 day slots (flexible)

    Returns list of dicts:
        [{"date": "2026-04-14", "day_label": "kal", "day_label_en": "tomorrow",
          "time": "11:00", "time_label": "subah 11 baje", "time_label_en": "11 AM"}]
    """
    today = datetime.now()
    slots = []

    if priority == "high":
        # Start from tomorrow, max 2 days out
        day_range = range(1, 3)
    elif priority == "medium":
        # Start from tomorrow, max 4 days out
        day_range = range(1, 5)
    else:
        # Start from day after tomorrow, max 6 days out
        day_range = range(2, 7)

    for offset in day_range:
        candidate = today + timedelta(days=offset)

        # Skip Sundays
        if candidate.weekday() not in CLINIC_DAYS:
            continue

        date_str = candidate.strftime("%Y-%m-%d")

        for slot_time in CLINIC_SLOTS:
            # Check if slot is already full
            booked_count = _count_bookings(date_str, slot_time)
            if booked_count >= MAX_BOOKINGS_PER_SLOT:
                continue

            slots.append({
                "date": date_str,
                "day_label": _day_label_hi(today, candidate),
                "day_label_en": _day_label_en(today, candidate),
                "time": slot_time,
                "time_label": _time_label_hi(slot_time),
                "time_label_en": _time_label_en(slot_time),
                "weekday": candidate.strftime("%A"),
            })

        # For high priority, stop at first day with available slots
        if priority == "high" and slots:
            break

    return slots


def get_slot_offer_text(priority: str, language: str = "hi") -> tuple:
    """
    Generate slot offer text based on priority and language.

    Returns: (offer_text, available_slots_list)
    """
    slots = get_slots(priority)

    if not slots:
        # No slots available — fallback
        if language == "en":
            return ("Our slots are currently full. We will call you back to schedule.", [])
        return ("Abhi slots full hain. Hum aapko wapas call karke schedule karenge.", [])

    if priority == "high":
        if language == "en":
            # Offer earliest slot with urgency
            s = slots[0]
            if len(slots) >= 2 and slots[0]["date"] == slots[1]["date"]:
                text = (
                    f"Based on your case, it's better not to delay. "
                    f"We have a slot {s['day_label_en']} — "
                    f"{slots[0]['time_label_en']} or {slots[1]['time_label_en']}."
                )
            else:
                text = (
                    f"Based on your case, it's better not to delay. "
                    f"We have a slot {s['day_label_en']} at {s['time_label_en']}."
                )
        else:
            s = slots[0]
            if len(slots) >= 2 and slots[0]["date"] == slots[1]["date"]:
                text = (
                    f"Aapka case dekh kar delay avoid karna better rahega. "
                    f"{s['day_label']} ek slot available hai — "
                    f"{slots[0]['time_label']} ya {slots[1]['time_label']}."
                )
            else:
                text = (
                    f"Aapka case dekh kar delay avoid karna better rahega. "
                    f"{s['day_label']} {s['time_label']} ka slot available hai."
                )

    elif priority == "medium":
        if language == "en":
            # Offer 2 days
            days_seen = []
            for sl in slots:
                if sl["day_label_en"] not in days_seen:
                    days_seen.append(sl["day_label_en"])
                if len(days_seen) >= 2:
                    break
            text = f"We have slots available {' or '.join(days_seen)}. Which day works for you?"
        else:
            days_seen = []
            for sl in slots:
                if sl["day_label"] not in days_seen:
                    days_seen.append(sl["day_label"])
                if len(days_seen) >= 2:
                    break
            text = f"Is week {' ya '.join(days_seen)} slots available hain. Kaunsa din theek rahega?"

    else:  # low
        if language == "en":
            text = "You can schedule whenever you are comfortable. I can check options for you. When would suit you?"
        else:
            text = "Aap jab comfortable ho tab schedule kar sakte hain. Main options check kar deta hoon. Kab theek rahega?"

    return (text, slots)


# ── Booking Creation ────────────────────────────────────────────────────────

def create_booking(
    session_id: str,
    phone: str,
    booking_date: str,
    booking_time: str,
    lead_priority: str,
    intent_level: str = "confirmed",
) -> bool:
    """
    Save a booking to the database.
    Updates the leads table with booking details.

    Returns True on success.
    """
    now = datetime.utcnow().isoformat() + "Z"

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        result = conn.execute(
            """
            UPDATE leads
               SET booking_date    = ?,
                   booking_time    = ?,
                   booking_status  = 'confirmed',
                   lead_priority   = ?,
                   intent_level    = ?,
                   call_outcome    = 'booked',
                   updated_at      = ?
             WHERE session_id      = ?
            """,
            (booking_date, booking_time, lead_priority, intent_level, now, session_id),
        )
        conn.commit()

        if result.rowcount > 0:
            log.info(
                f"BOOKING CREATED | session={session_id} | date={booking_date} | "
                f"time={booking_time} | priority={lead_priority}"
            )
            return True
        else:
            log.warning(f"BOOKING FAILED | session={session_id} not found in DB")
            return False
    except Exception as e:
        log.error(f"BOOKING ERROR | {e}", exc_info=True)
        return False
    finally:
        conn.close()


# ── WhatsApp Booking Confirmation ───────────────────────────────────────────

def send_whatsapp_confirmation(
    phone: str,
    booking_date: str,
    booking_time: str,
    language: str = "hi",
) -> bool:
    """
    Send WhatsApp confirmation message via Twilio after booking.
    Returns True on success, False on failure (non-blocking).
    """
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_number = os.environ.get("TWILIO_WHATSAPP_NUMBER", "")

    if not all([account_sid, auth_token, from_number]):
        log.warning("WhatsApp confirmation skipped — Twilio not configured")
        return False

    # Format the date for display
    try:
        dt = datetime.strptime(booking_date, "%Y-%m-%d")
        date_display_en = dt.strftime("%A, %d %B %Y")
        date_display_hi = date_display_en  # same format, acceptable for Hindi
    except ValueError:
        date_display_en = booking_date
        date_display_hi = booking_date

    time_display_en = _time_label_en(booking_time)
    time_display_hi = _time_label_hi(booking_time)

    if language == "en":
        message = (
            f"*Parivar Saathi — Booking Confirmed*\n\n"
            f"Your fertility counselling appointment is confirmed.\n\n"
            f"Date: {date_display_en}\n"
            f"Time: {time_display_en}\n\n"
            f"Our counsellor will call you at the scheduled time.\n"
            f"If you need to reschedule, reply to this message.\n\n"
            f"Take care."
        )
    else:
        message = (
            f"*परिवार साथी — बुकिंग कन्फर्म*\n\n"
            f"आपकी फर्टिलिटी काउंसलिंग अपॉइंटमेंट कन्फर्म हो गई है।\n\n"
            f"तारीख: {date_display_hi}\n"
            f"समय: {time_display_hi}\n\n"
            f"हमारे काउंसलर आपको तय समय पर कॉल करेंगे।\n"
            f"अगर आपको reschedule करना हो, तो इस मैसेज का जवाब दें।\n\n"
            f"अपना ख़्याल रखिए।"
        )

    # Clean phone number for WhatsApp
    clean_phone = phone.replace("whatsapp:", "").strip()
    if not clean_phone.startswith("+"):
        clean_phone = f"+{clean_phone}"
    wa_to = f"whatsapp:{clean_phone}"

    try:
        from twilio.rest import Client as TwilioClient
        client = TwilioClient(account_sid, auth_token)

        # Ensure from_number has whatsapp: prefix
        wa_from = from_number if from_number.startswith("whatsapp:") else f"whatsapp:{from_number}"

        msg = client.messages.create(
            to=wa_to,
            from_=wa_from,
            body=message,
        )
        log.info(f"WA CONFIRM SENT | to={wa_to} | sid={msg.sid}")
        return True

    except ImportError:
        log.error("WhatsApp confirmation failed: twilio package not installed")
        return False
    except Exception as e:
        log.error(f"WhatsApp confirmation failed: {e}", exc_info=True)
        return False


# ── Get All Bookings ────────────────────────────────────────────────────────

def get_all_bookings(
    status: Optional[str] = None,
    date: Optional[str] = None,
) -> list:
    """
    Return all leads that have bookings, with booking details.
    Optional filters by booking_status and booking_date.
    """
    query = """
        SELECT session_id, phone, lead_score, booking_date, booking_time,
               booking_status, lead_priority, intent_level, collected_data,
               created_at, updated_at
          FROM leads
         WHERE booking_date IS NOT NULL
    """
    params = []

    if status:
        query += " AND booking_status = ?"
        params.append(status)
    if date:
        query += " AND booking_date = ?"
        params.append(date)

    query += " ORDER BY booking_date ASC, booking_time ASC"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    import json
    bookings = []
    for row in rows:
        d = dict(row)
        try:
            d["collected_data"] = json.loads(d.get("collected_data") or "{}")
        except Exception:
            d["collected_data"] = {}
        bookings.append(d)

    return bookings


# ── Internal Helpers ────────────────────────────────────────────────────────

def _count_bookings(date_str: str, time_str: str) -> int:
    """Count existing confirmed bookings for a given date+time slot."""
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) FROM leads
             WHERE booking_date = ? AND booking_time = ?
               AND booking_status IN ('confirmed', 'pending')
            """,
            (date_str, time_str),
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0
    finally:
        conn.close()


def _day_label_hi(today: datetime, target: datetime) -> str:
    """Hindi day label relative to today."""
    diff = (target.date() - today.date()).days
    if diff == 0:
        return "aaj"
    elif diff == 1:
        return "kal"
    elif diff == 2:
        return "parson"
    else:
        weekday_hi = {
            0: "Monday", 1: "Tuesday", 2: "Wednesday",
            3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday",
        }
        return weekday_hi.get(target.weekday(), target.strftime("%A"))


def _day_label_en(today: datetime, target: datetime) -> str:
    """English day label relative to today."""
    diff = (target.date() - today.date()).days
    if diff == 0:
        return "today"
    elif diff == 1:
        return "tomorrow"
    elif diff == 2:
        return "day after tomorrow"
    else:
        return target.strftime("%A")


def _time_label_hi(time_str: str) -> str:
    """Hindi time label."""
    if time_str == "11:00":
        return "subah 11 baje"
    elif time_str == "15:00":
        return "dopahar 3 baje"
    return time_str


def _time_label_en(time_str: str) -> str:
    """English time label."""
    if time_str == "11:00":
        return "11 AM"
    elif time_str == "15:00":
        return "3 PM"
    return time_str
