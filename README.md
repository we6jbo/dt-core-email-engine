# dt-core – Email-driven decision engine

`dt-core` is a small email-driven decision engine designed to run on a Raspberry Pi or Linux server.
It polls an IMAP inbox for **dt-in** requests, runs a decision engine, and sends **dt-out** replies
through SMTP.

This project powers a workflow where a mobile app (Decision Tree Assistant) emails structured
requests like:

- `Request-ID`
- `Question`
- Optional extra context

`dt-core` reads the message, generates an answer, and replies by email.

## Features

- IMAP inbox polling for `dt-in RQ:` subjects.
- Parsing structured request bodies (Request-ID, Question, Extra context).
- Pluggable decision engine (`decision_engine.py`) for custom logic or AI.
- SMTP sending for `dt-out` replies and hourly status reports.
- Simple JSON status tracking in `state.json`.
- Optional self-healing hooks and restore scripts (`restore_github.sh`).

## Typical architecture

1. Android app (Decision Tree Assistant) sends a **dt-in** email to `master@we6jbobbs.org`.
2. `dt-core` on the Raspberry Pi polls the inbox and finds the request.
3. The decision engine processes the question and builds an answer.
4. `dt-core` sends a **dt-out** reply back to `we6jbo+decisiontree@gmail.com`.
5. Processed dt-in messages can be deleted from the mailbox for a clean queue.

## Configuration

All email and service configuration is handled in:

- `email_settings.py`
- `config_store.py`
- `status_manager.py`

You configure:

- IMAP host, port, username, and app password.
- SMTP host, port, username, and app password.
- Status email recipient.

## Running as a systemd service

`dt-core` is expected to run as a systemd service, for example:

```bash
sudo systemctl enable dt-core
sudo systemctl start dt-core
sudo systemctl status dt-core

