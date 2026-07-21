"""dt-core email orchestrator using Network Assistant human answers. Email transport remains unchanged."""
import subprocess, time
from datetime import datetime
from email_settings import load_email_settings
from email_receiver import fetch_new_requests, InboxNotCleanError
from email_sender import send_dt_out, send_status_email
from human_queue import enqueue_request, answered_requests, mark_sent
from status_manager import load_status_state, save_status_state, record_sent_email, record_received_request, record_error, should_send_status_email_now
POLL_INTERVAL_SECONDS=60
def main_loop_once():
    settings=load_email_settings(); state=load_status_state(); print('[dt-core] Polling INBOX...')
    try:
        requests=fetch_new_requests(settings,state); print(f'[dt-core] Fetched {len(requests)} request(s).')
    except InboxNotCleanError as exc:
        record_error(state,f'Error fetching requests: {exc}. Stopping dt-core.'); save_status_state(state); subprocess.run(['systemctl','stop','dt-core'],check=False); return
    except Exception as exc:
        record_error(state,f'Error fetching requests: {exc}'); save_status_state(state); return
    for request in requests:
        try:
            queue_id=enqueue_request(request); record_received_request(state,request); print(f'[dt-core] Queued request {request.request_id} as question {queue_id}.')
        except Exception as exc: record_error(state,f'Error queueing request {request.request_id}: {exc}')
    try: ready=answered_requests()
    except Exception as exc: record_error(state,f'Error reading answered queue: {exc}'); ready=[]
    for queue_id,request,answer_text in ready:
        if send_dt_out(settings,request,answer_text,state):
            mark_sent(queue_id); record_sent_email(state); print(f'[dt-core] Sent human answer for queue question {queue_id}.')
    now=datetime.utcnow()
    if should_send_status_email_now(state,now): send_status_email(settings,state,now)
    save_status_state(state)
def main():
    while True:
        try: main_loop_once()
        except Exception as exc: print(f'[dt-core] Error in main loop: {exc}')
        time.sleep(POLL_INTERVAL_SECONDS)
if __name__=='__main__': main()
