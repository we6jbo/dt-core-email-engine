"""dt-core email orchestrator with approved automatic and human answers."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from datetime import datetime

from email_receiver import InboxNotCleanError, fetch_new_requests
from email_sender import send_dt_out, send_status_email
from email_settings import load_email_settings
from human_queue import answered_requests, enqueue_request, mark_sent
from known_answers import (
    answer_existing_pending_questions,
    find_known_answer,
)
from status_manager import (
    load_status_state,
    record_error,
    record_received_request,
    record_sent_email,
    save_status_state,
    should_send_status_email_now,
)

POLL_INTERVAL_SECONDS = 60

GOVERNMENT_JOB_RESTORE_PHRASE = (
    "restore to the time i implemented government job search"
)
GOVERNMENT_JOB_RESTORE_TAG = "government-job-search-and-ai-story-v101"
GOVERNMENT_JOB_RESTORE_FLAG = Path(
    "/var/lib/dt-core/RCRA3.restore_older_version"
)


def _is_government_job_restore_request(question: str) -> bool:
    normalized = " ".join((question or "").strip().lower().split())
    accepted_phrases = {
        "restore to the time i implemented government job search",
        "restore back to when government job search implementation was implemented and when the story about ai was implemented",
    }
    return normalized in accepted_phrases

def _queue_government_job_restore() -> None:
    GOVERNMENT_JOB_RESTORE_FLAG.write_text(
        GOVERNMENT_JOB_RESTORE_TAG + "\n",
        encoding="utf-8",
    )


def main_loop_once() -> None:
    settings = load_email_settings()
    state = load_status_state()

    # Process existing queue work before contacting IMAP. This prevents an
    # IMAP timeout from blocking approved automatic and human answers.
    try:
        updated_before_fetch = answer_existing_pending_questions()

        for queue_id, match in updated_before_fetch:
            print(
                "[dt-core] Existing queue question "
                f"{queue_id} matched approved answer "
                f"{match.answer_id} "
                f"(confidence {match.confidence:.2f}).",
                flush=True,
            )
    except Exception as exc:
        print(
            "[dt-core] Error auto-answering existing questions "
            f"before IMAP: {exc}",
            flush=True,
        )
        record_error(
            state,
            f"Error auto-answering existing questions before IMAP: {exc}",
        )

    try:
        ready_before_fetch = answered_requests()
    except Exception as exc:
        print(
            f"[dt-core] Error reading answered queue before IMAP: {exc}",
            flush=True,
        )
        record_error(
            state,
            f"Error reading answered queue before IMAP: {exc}",
        )
        ready_before_fetch = []

    for queue_id, request, answer_text in ready_before_fetch:
        try:
            if send_dt_out(
                settings,
                request,
                answer_text,
                state,
            ):
                mark_sent(queue_id)
                record_sent_email(state)

                print(
                    "[dt-core] Sent pre-IMAP queue answer for question "
                    f"{queue_id}.",
                    flush=True,
                )
        except Exception as exc:
            print(
                "[dt-core] Error sending pre-IMAP queue answer "
                f"{queue_id}: {exc}",
                flush=True,
            )
            record_error(
                state,
                f"Error sending pre-IMAP queue answer {queue_id}: {exc}",
            )

    save_status_state(state)

    print("[dt-core] Polling INBOX...", flush=True)

    try:
        requests = fetch_new_requests(settings, state)
        print(
            f"[dt-core] Fetched {len(requests)} request(s).",
            flush=True,
        )
    except InboxNotCleanError as exc:
        print(
            f"[dt-core] Inbox safety error: {exc}. Stopping dt-core.",
            flush=True,
        )
        record_error(
            state,
            f"Error fetching requests: {exc}. Stopping dt-core.",
        )
        save_status_state(state)
        subprocess.run(
            ["systemctl", "stop", "dt-core"],
            check=False,
        )
        return
    except Exception as exc:
        print(
            f"[dt-core] Error fetching requests: {exc}",
            flush=True,
        )
        record_error(state, f"Error fetching requests: {exc}")
        save_status_state(state)
        return

    for request in requests:
        try:
            if _is_government_job_restore_request(request.question or ""):
                record_received_request(state, request)
                confirmation = (
                    "Restore request accepted. The Raspberry Pi will restore "
                    "dt-core to the protected government-job-search timepoint "
                    "at version 98 or newer."
                )
                if send_dt_out(settings, request, confirmation, state):
                    record_sent_email(state)
                    _queue_government_job_restore()
                    print(
                        "[dt-core] Government job search restore queued for "
                        f"{request.request_id}.",
                        flush=True,
                    )
                else:
                    queue_id = enqueue_request(request)
                    print(
                        "[dt-core] Restore confirmation could not be sent; "
                        f"request retained as queue question {queue_id}.",
                        flush=True,
                    )
                continue

            known = find_known_answer(request.question or "")

            if known is not None:
                record_received_request(state, request)

                print(
                    "[dt-core] Approved automatic answer matched "
                    f"{request.request_id}: {known.answer_id} "
                    f"(confidence {known.confidence:.2f}).",
                    flush=True,
                )

                if send_dt_out(
                    settings,
                    request,
                    known.answer,
                    state,
                ):
                    record_sent_email(state)
                    print(
                        "[dt-core] Sent approved automatic answer for "
                        f"{request.request_id}.",
                        flush=True,
                    )
                else:
                    # Preserve it in the queue so a failed or rate-limited
                    # email send can be retried during a later cycle.
                    queue_id = enqueue_request(request)
                    print(
                        "[dt-core] Automatic send was not completed; "
                        f"request retained as queue question {queue_id}.",
                        flush=True,
                    )

                continue

            queue_id = enqueue_request(request)
            record_received_request(state, request)

            print(
                f"[dt-core] Queued request {request.request_id} "
                f"as question {queue_id}.",
                flush=True,
            )

        except Exception as exc:
            record_error(
                state,
                f"Error processing request {request.request_id}: {exc}",
            )

    # This also checks questions that were already pending before the
    # automatic-answer feature was installed.
    try:
        updated = answer_existing_pending_questions()

        for queue_id, match in updated:
            print(
                "[dt-core] Existing queue question "
                f"{queue_id} matched approved answer "
                f"{match.answer_id} "
                f"(confidence {match.confidence:.2f}).",
                flush=True,
            )
    except Exception as exc:
        record_error(
            state,
            f"Error auto-answering existing pending questions: {exc}",
        )

    try:
        ready = answered_requests()
    except Exception as exc:
        record_error(
            state,
            f"Error reading answered queue: {exc}",
        )
        ready = []

    for queue_id, request, answer_text in ready:
        if send_dt_out(
            settings,
            request,
            answer_text,
            state,
        ):
            mark_sent(queue_id)
            record_sent_email(state)

            print(
                "[dt-core] Sent queue answer for question "
                f"{queue_id}.",
                flush=True,
            )

    now = datetime.utcnow()

    if should_send_status_email_now(state, now):
        send_status_email(settings, state, now)

    save_status_state(state)


def main() -> None:
    while True:
        try:
            main_loop_once()
        except Exception as exc:
            print(
                f"[dt-core] Error in main loop: {exc}",
                flush=True,
            )

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
