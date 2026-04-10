"""
lead_scorer.py
IVF Lead Intelligence Engine — v2.0

Replaces the simple 3-tier Hot/Warm/Cold with a composite scoring system
that factors in age, treatment history, duration, and clinical urgency.

Output: LeadProfile dataclass
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class LeadProfile:
    score: str = "Cold"
    priority_rank: int = 5          # 1 = call immediately, 5 = low priority
    severity_tag: str = "Early Monitoring"
    urgency_flags: List[str] = field(default_factory=list)
    ivf_probability: str = "Low"
    ovarian_reserve_concern: bool = False
    follow_up_hours: int = 72       # suggested follow-up interval in hours


def score_lead(
    duration_months: Optional[float],
    age: Optional[str],
    treatment_history: Optional[str],
) -> LeadProfile:
    """
    Composite IVF lead scoring. Considers:
      1. Treatment history (IVF failure → immediate priority)
      2. Duration (>3 years → urgent)
      3. Age (≥35 → add urgency)
      4. Combined patterns (age 35+ + 2+ years → escalate)

    Returns a LeadProfile with score, priority_rank, severity_tag,
    ivf_probability, ovarian_reserve_concern, follow_up_hours, urgency_flags.
    """
    profile = LeadProfile()
    th = (treatment_history or "").lower()
    dur = duration_months or 0
    age_val = _parse_age_numeric(age)
    flags = []

    # ── Treatment history signals ─────────────────────────────────────────────
    if "ivf" in th and ("fail" in th or "multiple" in th):
        profile.score = "Hot"
        profile.priority_rank = 1
        profile.severity_tag = "IVF Failure — Re-evaluation Needed"
        profile.ivf_probability = "High"
        flags.append("Previous IVF failure — high emotional investment")
        flags.append("Patient likely has detailed medical history")
        flags.append("Strong decision intent — needs re-engagement strategy")

    elif "ivf" in th:
        profile.score = "Hot"
        profile.priority_rank = 1
        profile.severity_tag = "Prior IVF Treatment"
        profile.ivf_probability = "High"
        flags.append("Has undergone IVF — informed decision maker")
        flags.append("Likely comparing clinics — differentiation critical")

    elif "iui" in th:
        profile.score = "Warm" if dur < 36 else "Hot"
        profile.priority_rank = 2
        profile.severity_tag = "IUI History — IVF Next Step Likely"
        profile.ivf_probability = "Moderate"
        flags.append("IUI attempted — may be ready to escalate to IVF")

    # ── Duration signals (override upward if stronger) ────────────────────────
    if dur > 48:
        if profile.priority_rank > 1:
            profile.score = "Hot"
            profile.priority_rank = 1
            profile.severity_tag = "Long-term Infertility — Critical Urgency"
            profile.ivf_probability = "High"
        flags.append("Trying >4 years — biological clock concern critical")

    elif dur > 36:
        if profile.priority_rank > 2:
            profile.score = "Hot"
            profile.priority_rank = 2
            profile.severity_tag = "Extended Infertility — Urgent"
            profile.ivf_probability = "High"
        flags.append("Trying >3 years — IVF evaluation strongly recommended")

    elif dur >= 24:
        if profile.priority_rank > 3:
            profile.score = "Warm"
            profile.priority_rank = 3
            profile.severity_tag = "Moderate Duration — Evaluation Advised"
            profile.ivf_probability = "Moderate"
        flags.append("Trying 2+ years — fertility workup recommended")

    elif dur >= 12:
        if profile.priority_rank > 4:
            profile.score = "Warm"
            profile.priority_rank = 4
            profile.severity_tag = "Early Infertility — Investigation Advised"
            profile.ivf_probability = "Low"
        flags.append("Trying 1+ year — fertility evaluation appropriate")

    else:
        if profile.priority_rank == 5:
            profile.score = "Cold"
            profile.severity_tag = "Early Stage — Natural Conception Possible"
            profile.ivf_probability = "Low"
        flags.append("Early stage — reassurance and monitoring first")

    # ── Age signals (additive urgency modifier) ───────────────────────────────
    if age_val is not None:
        if age_val >= 38:
            profile.ovarian_reserve_concern = True
            profile.priority_rank = max(1, profile.priority_rank - 2)
            profile.score = "Hot"
            flags.append(f"Age {int(age_val)} — diminished ovarian reserve risk")
            flags.append("Immediate AMH test and specialist review advised")

        elif age_val >= 35:
            profile.ovarian_reserve_concern = True
            profile.priority_rank = max(1, profile.priority_rank - 1)
            if dur >= 12:
                profile.score = "Hot"
            flags.append(f"Age {int(age_val)} — fertility window narrowing")
            flags.append("Timely evaluation strongly advised")

        elif age_val >= 30 and dur >= 24:
            flags.append(f"Age {int(age_val)} with 2+ years trying — evaluation overdue")

        elif age_val < 30 and dur < 12:
            # Young + early stage — reassure, don't medicalise
            if "none" in th or th.strip() == "":
                flags.append("Young couple, early stage — natural conception still likely")

    # ── Follow-up timing based on final priority ──────────────────────────────
    follow_up_map = {1: 4, 2: 8, 3: 24, 4: 48, 5: 72}
    profile.follow_up_hours = follow_up_map.get(profile.priority_rank, 72)
    profile.urgency_flags = flags

    return profile


def _parse_age_numeric(age_str: Optional[str]) -> Optional[float]:
    """Extract numeric age from '35', '30-35', 'mid thirties', etc."""
    if age_str is None:
        return None

    # Range: take midpoint
    range_match = re.search(r'(\d+)\s*[-–to]+\s*(\d+)', str(age_str))
    if range_match:
        return (float(range_match.group(1)) + float(range_match.group(2))) / 2

    # Bare number
    num = re.search(r'\b(\d{2})\b', str(age_str))
    if num:
        return float(num.group(1))

    # Verbal phrases
    verbal = {
        "early twenties": 22, "mid twenties": 25, "late twenties": 28,
        "early thirties": 31, "mid thirties": 35, "late thirties": 37,
        "early forties": 41, "mid forties": 45,
    }
    lower = str(age_str).lower()
    for phrase, val in verbal.items():
        if phrase in lower:
            return float(val)

    return None
