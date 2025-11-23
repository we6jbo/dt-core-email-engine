"""
status_manager: track flood control and status information.

Stores state in /var/lib/dt-core/state.json and /var/lib/dt-core/status.txt.

- status.txt: simple integer count of all emails sent since first run.
- state.json: JSON dict with keys:
    {
      "total_sent": int,
      "last_sent_ts": "ISO8601",
      "last_received_request_id": "YYYY-MM-DD-HHMMSS",
      "last_status_hour": "YYYY-MM-DD-HH",
      "last_error": "text or null"
    }
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

STATE_DIR = Path("/var/lib/dt-core")
STATE_JSON = STATE_DIR / "state.json"
STATUS_TXT = STATE_DIR / "status.txt"


@dataclass
class StatusState:
    total_sent: int = 0
    last_sent_ts: Optional[str] = None
    last_received_request_id: Optional[str] = None
    last_status_hour: Optional[str] = None
    last_error: Optional[str] = None


def _ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_status_state() -> StatusState:
    _ensure_dirs()
    if STATE_JSON.exists():
        try:
            data: Dict[str, Any] = json.loads(STATE_JSON.read_text())
            return StatusState(
                total_sent=int(data.get("total_sent", 0)),
                last_sent_ts=data.get("last_sent_ts"),
                last_received_request_id=data.get("last_received_request_id"),
                last_status_hour=data.get("last_status_hour"),
                last_error=data.get("last_error"),
            )
        except Exception:
            # Fall back to defaults if the file is corrupt.
            pass
    # Initialize status.txt if missing
    if not STATUS_TXT.exists():
        STATUS_TXT.write_text("0\n")
    return StatusState()


def save_status_state(state: StatusState) -> None:
    _ensure_dirs()
    STATE_JSON.write_text(json.dumps(asdict(state), indent=2))
    STATUS_TXT.write_text(f"{state.total_sent}\n")


def record_sent_email(state: StatusState) -> None:
    state.total_sent += 1
    state.last_sent_ts = datetime.utcnow().isoformat(timespec="seconds")


def record_received_request(state: StatusState, request) -> None:
    # request has attribute request_id in YYYY-MM-DD-HHMMSS format.
    state.last_received_request_id = request.request_id


def record_error(state: StatusState, message: str) -> None:
    state.last_error = message


def _seconds_since_last_send(state: StatusState, now: datetime) -> float:
    if not state.last_sent_ts:
        return 999999.0
    try:
        last = datetime.fromisoformat(state.last_sent_ts)
    except Exception:
        return 999999.0
    return (now - last).total_seconds()


def can_send_now(state: StatusState, now: datetime, min_interval_seconds: int = 10) -> bool:
    """
    Very simple flood protection: enforce a minimum interval between sends.
    You can tighten this later if you need stronger limits.
    """
    return _seconds_since_last_send(state, now) >= min_interval_seconds


def request_id_to_hour(request_id: str) -> str:
    """
    Convert YYYY-MM-DD-HHMMSS -> YYYY-MM-DD-HH
    Example: 2025-11-18-091550 -> 2025-11-18-09
    """
    return request_id[:13]


def should_send_status_email_now(state: StatusState, now: datetime) -> bool:
    """
    Decide whether we should send an hourly status email.

    Rule:
    - We have received at least one request (last_received_request_id not None)
    - And we have not yet sent a status email for that hour (last_status_hour != that hour)
    - And the current UTC minute is 0 (top of the hour) OR
      more than 65 minutes have passed since that hour.
    """
    if not state.last_received_request_id:
        return False

    last_hour = request_id_to_hour(state.last_received_request_id)
    if state.last_status_hour == last_hour:
        return False

    # Prefer to send at the top of the hour
    if now.minute == 0:
        return True

    # Fallback: if we missed the top of the hour, send after a delay
    try:
        dt = datetime.strptime(last_hour, "%Y-%m-%d-%H")
        if (now - dt) > timedelta(minutes=65):
            return True
    except Exception:
        # If parsing fails, play it safe and do not send.
        return False

    return False

