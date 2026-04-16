"""Lead scoring — deterministic, no ML."""
from typing import Tuple
from app.models.session import LeadData
from app.config import (
    AGE_THRESHOLD, AGE_BONUS,
    DURATION_THRESHOLD_YEARS, DURATION_BONUS,
    PRIOR_IVF_BONUS,
    CATEGORY_HIGH_MIN, CATEGORY_MEDIUM_MIN,
)


def score_lead(lead: LeadData) -> Tuple[int, str]:
    """
    Scoring rules:
        age >= 30           +2
        duration >= 2 yrs   +3
        prior IVF           +3

    Category:
        HIGH    >= 6
        MEDIUM  3–5
        LOW     0–2
    """
    score = 0
    if lead.age is not None and lead.age >= AGE_THRESHOLD:
        score += AGE_BONUS
    if lead.duration_months is not None and lead.duration_months >= DURATION_THRESHOLD_YEARS * 12:
        score += DURATION_BONUS
    if lead.prior_ivf is True:
        score += PRIOR_IVF_BONUS

    if score >= CATEGORY_HIGH_MIN:
        category = "HIGH"
    elif score >= CATEGORY_MEDIUM_MIN:
        category = "MEDIUM"
    else:
        category = "LOW"
    return score, category
