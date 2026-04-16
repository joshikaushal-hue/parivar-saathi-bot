"""
Helper — trigger an outbound Twilio call that lands on /voice/incoming.

Usage:
  export TWILIO_ACCOUNT_SID=...
  export TWILIO_AUTH_TOKEN=...
  export TWILIO_NUMBER=+1...
  export PUBLIC_BASE_URL=https://your-app.onrender.com
  python scripts/place_outbound_call.py +919831844401
"""
import os
import sys
from twilio.rest import Client


def main(to_number: str):
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    tok = os.environ["TWILIO_AUTH_TOKEN"]
    from_ = os.environ["TWILIO_NUMBER"]
    base = os.environ["PUBLIC_BASE_URL"].rstrip("/")

    client = Client(sid, tok)
    call = client.calls.create(
        to=to_number,
        from_=from_,
        url=f"{base}/voice/incoming",
        method="POST",
        status_callback=f"{base}/voice/status",
        status_callback_method="POST",
        status_callback_event=["initiated", "ringing", "answered", "completed"],
    )
    print(f"placed call_sid={call.sid} to={to_number}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: place_outbound_call.py +E164NUMBER")
        sys.exit(1)
    main(sys.argv[1])
