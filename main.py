"""
Main orchestrator loop for dt-core:
- Poll inbox for new dt-in requests.
- For each request, decide on an answer.
- Send dt-out replies (with simple flood protection).
- Maintain status counters and hourly status emails.
"""

import time
from datetime import datetime

# *** IMPORTANT ***
# These must be absolute imports because main.py is run directly as a script.
from email_settings import load_email_settings
from email_receiver import fetch_new_requests, InboxNotCleanError
import subprocess
from decision_engine import generate_answer
from email_sender import send_dt_out, send_status_email
from status_manager import (
    load_status_state,
    save_status_state,
    record_sent_email,
    record_received_request,
    record_error,
    should_send_status_email_now,
)

POLL_INTERVAL_SECONDS = 60

def main_loop_once() -> None:
    settings = load_email_settings()
    state = load_status_state()
    print("[dt-core] Polling INBOX...")

       # 1. Fetch new dt-in requests
    try:
        requests = fetch_new_requests(settings, state)
        print(f"[dt-core] Fetched {len(requests)} request(s).")
    except InboxNotCleanError as e:
        record_error(state, f"Error fetching requests: {e}. Stopping dt-core.")
        save_status_state(state)
        try:
            subprocess.run(["systemctl", "stop", "dt-core"], check=False)
        except Exception as e2:
            # Instead of printing, create the file
            try:
                with open("/var/lib/dt-core/RCRA3.restore_older_version", "w") as f:
                    f.write(str(e2))
            except Exception:
                pass
        return
    except Exception as e:
        record_error(state, f"Error fetching requests: {e}")
        save_status_state(state)
        return
 

    # 2. Process each request
    for req in requests:
        try:
            answer_text = generate_answer(req)
        except Exception as e:
            record_error(state, f"Error in decision engine for {req.request_id}: {e}")
            continue

        sent = send_dt_out(settings, req, answer_text, state)
        if sent:
            record_sent_email(state)
            record_received_request(state, req)

    # 3. Maybe send hourly status email
    now = datetime.utcnow()
    if should_send_status_email_now(state, now):
        send_status_email(settings, state, now)

    # 4. Persist state
    save_status_state(state)


def main() -> None:
    while True:
        try:
            main_loop_once()
        except Exception as e:
            # For now just print; later you can log to journald or a file.
            print(f"[dt-core] Error in main loop: {e}")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

