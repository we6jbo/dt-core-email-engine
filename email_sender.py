"""
email_sender: send dt-out and status emails via SMTP.
"""

import smtplib
from email.message import EmailMessage
from datetime import datetime

from email_settings import EmailSettings
from models import DTRequest
from status_manager import (
    StatusState,
    can_send_now,
    request_id_to_hour,
    record_error,
)


def _build_dt_out_message(
    settings: EmailSettings,
    request: DTRequest,
    answer_text: str,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.username 
    msg["To"] = settings.status_recipient
    # Subject must echo the incoming timestamp exactly.
    msg["Subject"] = f"dt-out RQ:{request.request_id}"
    msg.set_content(
        f"DT-OUT for Request-ID {request.request_id}\n\n"
        f"Question:\n{request.question}\n\n"
        f"Answer:\n{answer_text}\n"
    )
    return msg


def send_dt_out(
    settings: EmailSettings,
    request: DTRequest,
    answer_text: str,
    state: StatusState,
) -> bool:
    """
    Send a dt-out email if flood protection allows.
    Returns True if the message was sent, False otherwise.
    """
    now = datetime.utcnow()
    if not can_send_now(state, now):
        msg = f"Flood protection: skipping dt-out send for {request.request_id}"
        print("[dt-core]", msg)
        record_error(state, msg)
        return False

    msg = _build_dt_out_message(settings, request, answer_text)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
            s.starttls()
            s.login(settings.username, settings.password)
            s.send_message(msg)
    except Exception as e:
        err = f"SMTP error sending dt-out for {request.request_id}: {e}"
        print("[dt-core]", err)
        record_error(state, err)
        return False

    print("[dt-core] Sent dt-out for", request.request_id)
    return True


def send_status_email(settings: EmailSettings, state: StatusState, now: datetime) -> None:
    """
    Send an hourly status email summarizing total sent count and last error.

    Subject: "statusinfo YYYY-MM-DD-HH"
    where the hour is derived from the last request we received.
    """
    if not state.last_received_request_id:
        return

    hour_str = request_id_to_hour(state.last_received_request_id)
    subject = f"statusinfo {hour_str}"

    body_lines = [
        f"dt-core status for hour {hour_str}",
        "",
        f"Total emails sent (lifetime): {state.total_sent}",
        f"Last sent timestamp (UTC): {state.last_sent_ts or 'never'}",
        f"Last error: {state.last_error or 'none recorded'}",
    ]
    body = "\n".join(body_lines) + "\n"

    msg = EmailMessage()
    msg["From"] = settings.reply_address
    msg["To"] = settings.status_recipient
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
            s.starttls()
            s.login(settings.username, settings.password)
            s.send_message(msg)
    except Exception as e:
        err = f"SMTP error sending status email for hour {hour_str}: {e}"
        print("[dt-core]", err)
        record_error(state, err)
        return

    print("[dt-core] Sent status email for hour", hour_str)
    state.last_status_hour = hour_str

