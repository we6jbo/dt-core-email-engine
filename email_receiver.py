#"""
#email_receiver: read-only access to the inbox that receives dt-in requests.
#
#Uses standard IMAP (e.g. Gmail IMAP with an app password).
#"""
#
#email_receiver: read-only access to the inbox that receives dt-in requests.
#
#Uses standard IMAP (e.g. Gmail IMAP with an app password).
#"""
#joneal 11-22-2025 5:46AM
import imaplib
import email
from email.message import Message
from email.header import decode_header
from typing import List

from email_settings import EmailSettings
from models import DTRequest
from status_manager import StatusState

class InboxNotCleanError(RuntimeError):
    """Raised when INBOX still has dt-in messages after delete verification."""
    pass


def _decode_header_value(value):
    if value is None:
        return ""

    # Always convert to a *string* before calling decode_header
    if isinstance(value, bytes):
        value_str = value.decode("utf-8", errors="ignore")
    else:
        value_str = str(value)

    parts = decode_header(value_str)
    decoded_chunks = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            decoded_chunks.append(chunk.decode(enc or "utf-8", errors="ignore"))
        else:
            decoded_chunks.append(chunk)
    return "".join(decoded_chunks)

def _extract_text_body(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in disp.lower():
                payload = part.get_payload(decode=True) or b""
                return payload.decode(
                    part.get_content_charset() or "utf-8",
                    errors="ignore",
                )
        return ""
    else:
        payload = msg.get_payload(decode=True) or b""
        return payload.decode(
            msg.get_content_charset() or "utf-8",
            errors="ignore",
        )


def _parse_request_from_body(body: str, fallback_request_id: str, msg_uid: str) -> DTRequest:
#    """
#    Expect a body like:
#
#        Request-ID: 2025-11-16-175120
#
#        Question:
#        Can you send a response back
#
#        Extra context (optional):
#        - Sent from Decision Tree Android app.
#    """
    lines = [line.rstrip("\r") for line in body.splitlines()]
    request_id = fallback_request_id
    question_lines: list[str] = []
    extra_lines: list[str] = []

    mode = "search"
    for line in lines:
        if line.startswith("Request-ID:"):
            request_id = line.split(":", 1)[1].strip() or request_id
        elif line.strip().lower() == "question:":
            mode = "question"
            continue
        elif line.lower().startswith("extra context"):
            mode = "extra"
            continue
        else:
            if mode == "question":
                question_lines.append(line)
            elif mode == "extra":
                extra_lines.append(line)

    question = "\n".join(question_lines).strip()
    extra_context = "\n".join(extra_lines).strip() or None

    return DTRequest(
        request_id=request_id,
        question=question or "(no question body found)",
        raw_email_id=msg_uid,
        timestamp=request_id,
        extra_context=extra_context,
    )


def fetch_new_requests(settings: EmailSettings, state: StatusState) -> List[DTRequest]:
#    """
#    Connect to IMAP, find UNSEEN messages whose subject starts with 'dt-in RQ:',
#    parse them into DTRequest objects, and mark them as SEEN.
#    """
    requests: List[DTRequest] = []
    delete_any = False
    imap = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    imap.login(settings.username, settings.password)
    imap.select("INBOX")

    # Look for messages whose subject contains "dt-in RQ:"
    typ, data = imap.search(None, 'SUBJECT', '"dt-in"')
    if typ != "OK":
        imap.logout()
        return requests

    for num in data[0].split():
        typ, msg_data = imap.fetch(num, "(RFC822)")
        if typ != "OK":
            continue

        msg = email.message_from_bytes(msg_data[0][1])
        subject = _decode_header_value(msg.get("Subject", ""))
        # Accept "dt-in RQ:2025-11-18-091550" or "dt-in RQ: 2025-11-18-091550"
        lower_subj = subject.lower().replace(" ", "")
        if not lower_subj.startswith("dt-inrq:"):
            # Not a dt-in message; mark as seen and skip.
            imap.store(num, "+FLAGS", "\\Seen")
            continue

        # Extract the request-id portion (after "RQ:")
        try:
            after = subject.split("RQ:", 1)[1].strip()
        except IndexError:
            after = ""

        request_id = after
        body_text = _extract_text_body(msg)
        uid = num.decode("ascii", errors="ignore")

        req = _parse_request_from_body(body_text, request_id, uid)
        requests.append(req)

        # Mark as seen so we do not reprocess.
        imap.store(num, "+FLAGS", "\\Deleted")
        delete_any = True
    if deleted_any:
        imap.expunge()
        # Verify there are no remaining dt-in messages
        typ2, data2 = imap.search(None, 'SUBJECT', '"dt-in RQ"')
        if typ2 == "OK" and data2 and data2[0].strip():
            # There are still dt-in messages left, so raise an error.
            raise InboxNotCleanError("INBOX still has dt-in messages after delete/verify.")
    imap.close()
    imap.logout()
    return requests

