"""
dashboard.py
Phase 4 — Counselor CRM Dashboard

A lightweight HTML dashboard served by FastAPI.
No React, no build step — just server-rendered HTML with inline CSS/JS.

Endpoints:
  GET /dashboard           — Main dashboard page
  GET /dashboard/api/stats — JSON stats for AJAX refresh

Features:
  - Today's bookings (priority-colored)
  - Lead pipeline summary
  - Follow-up queue
  - Booking calendar view
  - Mobile-friendly (counselors use phones)
"""

import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger("ivf_engine")

DB_PATH = "leads.db"

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ── Dashboard Data Queries ──────────────────────────────────────────────────

def _get_dashboard_data(date_filter: Optional[str] = None) -> dict:
    """Fetch all data needed for the dashboard in a single DB call."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # All leads
        leads = [dict(r) for r in conn.execute(
            "SELECT * FROM leads ORDER BY created_at DESC"
        ).fetchall()]

        # Parse JSON fields
        for lead in leads:
            try:
                lead["collected_data"] = json.loads(lead.get("collected_data") or "{}")
            except Exception:
                lead["collected_data"] = {}
            try:
                lead["counselor_brief"] = json.loads(lead.get("counselor_brief") or "null")
            except Exception:
                lead["counselor_brief"] = None
    finally:
        conn.close()

    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    # Categorize
    total = len(leads)
    hot = sum(1 for l in leads if l.get("lead_score") == "Hot")
    warm = sum(1 for l in leads if l.get("lead_score") == "Warm")
    cold = sum(1 for l in leads if l.get("lead_score") == "Cold")

    booked = [l for l in leads if l.get("booking_status") == "confirmed"]
    today_bookings = [l for l in booked if l.get("booking_date") == today]
    tomorrow_bookings = [l for l in booked if l.get("booking_date") == tomorrow]

    # Follow-ups needed
    now_iso = datetime.utcnow().isoformat() + "Z"
    follow_ups = [
        l for l in leads
        if l.get("follow_up_at") and l["follow_up_at"] <= now_iso
        and l.get("call_outcome") not in ("booked", "consultation_done", "not_interested")
    ]

    # Priority breakdown of bookings
    high_bookings = sum(1 for l in booked if l.get("lead_priority") == "high")
    medium_bookings = sum(1 for l in booked if l.get("lead_priority") == "medium")
    low_bookings = sum(1 for l in booked if l.get("lead_priority") == "low")

    # Recent activity (last 24h)
    yesterday = (datetime.utcnow() - timedelta(hours=24)).isoformat() + "Z"
    recent = [l for l in leads if l.get("created_at", "") >= yesterday]

    return {
        "total_leads": total,
        "hot": hot,
        "warm": warm,
        "cold": cold,
        "total_bookings": len(booked),
        "today_bookings": today_bookings,
        "tomorrow_bookings": tomorrow_bookings,
        "follow_ups": follow_ups,
        "high_bookings": high_bookings,
        "medium_bookings": medium_bookings,
        "low_bookings": low_bookings,
        "recent_leads": len(recent),
        "all_bookings": booked,
        "all_leads": leads,
        "today": today,
    }


# ── JSON Stats Endpoint ─────────────────────────────────────────────────────

@router.get("/api/stats")
async def dashboard_stats():
    """JSON stats for AJAX refresh."""
    try:
        data = _get_dashboard_data()
        # Remove full lead objects (too heavy for API)
        return JSONResponse({
            "total_leads": data["total_leads"],
            "hot": data["hot"],
            "warm": data["warm"],
            "cold": data["cold"],
            "total_bookings": data["total_bookings"],
            "today_bookings_count": len(data["today_bookings"]),
            "tomorrow_bookings_count": len(data["tomorrow_bookings"]),
            "follow_ups_count": len(data["follow_ups"]),
            "high_bookings": data["high_bookings"],
            "medium_bookings": data["medium_bookings"],
            "low_bookings": data["low_bookings"],
            "recent_leads": data["recent_leads"],
        })
    except Exception as exc:
        log.error(f"/dashboard/api/stats error: {exc}", exc_info=True)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Main Dashboard HTML ─────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard_page():
    """Serve the CRM dashboard as a single HTML page."""
    try:
        data = _get_dashboard_data()
    except Exception as exc:
        log.error(f"/dashboard error: {exc}", exc_info=True)
        return HTMLResponse(f"<h1>Dashboard Error</h1><p>{exc}</p>", status_code=500)

    # Build today's bookings rows
    today_rows = ""
    for b in data["today_bookings"]:
        cd = b.get("collected_data", {})
        priority = b.get("lead_priority", "?")
        priority_class = f"priority-{priority}"
        phone = b.get("phone", "N/A")
        time_str = b.get("booking_time", "?")
        time_label = "11 AM" if time_str == "11:00" else ("3 PM" if time_str == "15:00" else time_str)
        age = cd.get("age", "?")
        treatment = cd.get("treatment_history", "?")
        today_rows += f"""
        <tr class="{priority_class}">
            <td>{time_label}</td>
            <td>{phone}</td>
            <td><span class="badge badge-{priority}">{priority.upper()}</span></td>
            <td>{age}</td>
            <td>{treatment}</td>
        </tr>"""

    if not today_rows:
        today_rows = '<tr><td colspan="5" class="empty">No bookings today</td></tr>'

    # Build tomorrow's bookings rows
    tomorrow_rows = ""
    for b in data["tomorrow_bookings"]:
        cd = b.get("collected_data", {})
        priority = b.get("lead_priority", "?")
        phone = b.get("phone", "N/A")
        time_str = b.get("booking_time", "?")
        time_label = "11 AM" if time_str == "11:00" else ("3 PM" if time_str == "15:00" else time_str)
        tomorrow_rows += f"""
        <tr>
            <td>{time_label}</td>
            <td>{phone}</td>
            <td><span class="badge badge-{priority}">{priority.upper()}</span></td>
            <td>{cd.get('age', '?')}</td>
        </tr>"""

    if not tomorrow_rows:
        tomorrow_rows = '<tr><td colspan="4" class="empty">No bookings tomorrow</td></tr>'

    # Build follow-up rows
    followup_rows = ""
    for f in data["follow_ups"][:10]:
        phone = f.get("phone", "N/A")
        score = f.get("lead_score", "?")
        status = f.get("status", "?")
        followup_rows += f"""
        <tr>
            <td>{phone}</td>
            <td><span class="badge badge-score-{score.lower()}">{score}</span></td>
            <td>{status}</td>
            <td>{f.get('follow_up_at', '?')[:10]}</td>
        </tr>"""

    if not followup_rows:
        followup_rows = '<tr><td colspan="4" class="empty">No follow-ups due</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Parivar Saathi — Counselor Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f7fa;
            color: #1a1a2e;
            line-height: 1.5;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            text-align: center;
        }}
        .header h1 {{ font-size: 1.4em; font-weight: 600; }}
        .header p {{ opacity: 0.85; font-size: 0.9em; margin-top: 4px; }}

        .container {{ max-width: 900px; margin: 0 auto; padding: 16px; }}

        /* Stats Cards */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }}
        .stat-card {{
            background: white;
            border-radius: 12px;
            padding: 16px;
            text-align: center;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        .stat-card .number {{
            font-size: 2em;
            font-weight: 700;
            line-height: 1.2;
        }}
        .stat-card .label {{
            font-size: 0.75em;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-top: 4px;
        }}
        .stat-card.hot .number {{ color: #e74c3c; }}
        .stat-card.warm .number {{ color: #f39c12; }}
        .stat-card.cold .number {{ color: #3498db; }}
        .stat-card.booked .number {{ color: #27ae60; }}

        /* Sections */
        .section {{
            background: white;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        .section h2 {{
            font-size: 1.1em;
            font-weight: 600;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        /* Tables */
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9em;
        }}
        th {{
            text-align: left;
            padding: 8px 12px;
            background: #f8f9fa;
            font-weight: 600;
            font-size: 0.8em;
            text-transform: uppercase;
            color: #666;
            border-bottom: 2px solid #eee;
        }}
        td {{
            padding: 10px 12px;
            border-bottom: 1px solid #f0f0f0;
        }}
        tr:last-child td {{ border-bottom: none; }}

        .priority-high {{ border-left: 3px solid #e74c3c; }}
        .priority-medium {{ border-left: 3px solid #f39c12; }}
        .priority-low {{ border-left: 3px solid #27ae60; }}

        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.75em;
            font-weight: 600;
        }}
        .badge-high {{ background: #fde8e8; color: #e74c3c; }}
        .badge-medium {{ background: #fef3e2; color: #f39c12; }}
        .badge-low {{ background: #e8f5e9; color: #27ae60; }}
        .badge-score-hot {{ background: #fde8e8; color: #e74c3c; }}
        .badge-score-warm {{ background: #fef3e2; color: #f39c12; }}
        .badge-score-cold {{ background: #e3f2fd; color: #3498db; }}

        .empty {{
            text-align: center;
            color: #999;
            padding: 20px !important;
            font-style: italic;
        }}

        /* Refresh button */
        .refresh-btn {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            font-size: 1.5em;
            cursor: pointer;
            box-shadow: 0 2px 10px rgba(102,126,234,0.4);
        }}
        .refresh-btn:hover {{ background: #5a6fd6; }}

        @media (max-width: 600px) {{
            .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
            table {{ font-size: 0.8em; }}
            td, th {{ padding: 6px 8px; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Parivar Saathi</h1>
        <p>Counselor Dashboard — {data['today']}</p>
    </div>

    <div class="container">
        <!-- Stats Overview -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="number">{data['total_leads']}</div>
                <div class="label">Total Leads</div>
            </div>
            <div class="stat-card hot">
                <div class="number">{data['hot']}</div>
                <div class="label">Hot</div>
            </div>
            <div class="stat-card warm">
                <div class="number">{data['warm']}</div>
                <div class="label">Warm</div>
            </div>
            <div class="stat-card booked">
                <div class="number">{data['total_bookings']}</div>
                <div class="label">Booked</div>
            </div>
            <div class="stat-card">
                <div class="number">{len(data['follow_ups'])}</div>
                <div class="label">Follow-ups</div>
            </div>
            <div class="stat-card">
                <div class="number">{data['recent_leads']}</div>
                <div class="label">Last 24h</div>
            </div>
        </div>

        <!-- Today's Bookings -->
        <div class="section">
            <h2>Today's Appointments ({len(data['today_bookings'])})</h2>
            <table>
                <thead>
                    <tr><th>Time</th><th>Phone</th><th>Priority</th><th>Age</th><th>Treatment</th></tr>
                </thead>
                <tbody>
                    {today_rows}
                </tbody>
            </table>
        </div>

        <!-- Tomorrow's Bookings -->
        <div class="section">
            <h2>Tomorrow ({len(data['tomorrow_bookings'])})</h2>
            <table>
                <thead>
                    <tr><th>Time</th><th>Phone</th><th>Priority</th><th>Age</th></tr>
                </thead>
                <tbody>
                    {tomorrow_rows}
                </tbody>
            </table>
        </div>

        <!-- Follow-ups Due -->
        <div class="section">
            <h2>Follow-ups Due ({len(data['follow_ups'])})</h2>
            <table>
                <thead>
                    <tr><th>Phone</th><th>Score</th><th>Status</th><th>Due</th></tr>
                </thead>
                <tbody>
                    {followup_rows}
                </tbody>
            </table>
        </div>
    </div>

    <button class="refresh-btn" onclick="location.reload()">&#x21bb;</button>
</body>
</html>"""

    return HTMLResponse(html)
