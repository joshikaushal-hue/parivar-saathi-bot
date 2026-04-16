from app.models.session import LeadData
from app.services.scoring import score_lead


def test_low_lead():
    lead = LeadData(age=25, duration_months=6, prior_ivf=False)
    score, cat = score_lead(lead)
    assert score == 0
    assert cat == "LOW"


def test_medium_lead_age_plus_duration():
    lead = LeadData(age=32, duration_months=30, prior_ivf=False)
    score, cat = score_lead(lead)
    assert score == 5
    assert cat == "MEDIUM"


def test_high_lead_all_signals():
    lead = LeadData(age=34, duration_months=36, prior_ivf=True)
    score, cat = score_lead(lead)
    assert score == 8
    assert cat == "HIGH"


def test_missing_fields_ok():
    lead = LeadData()
    score, cat = score_lead(lead)
    assert score == 0
    assert cat == "LOW"
