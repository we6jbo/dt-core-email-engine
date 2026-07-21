#!/usr/bin/env python3
"""Shared SQLite queue between dt-core (pi) and Network Assistant (bayparkai)."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from models import DTRequest
DB_PATH = Path('/var/lib/baypark-decision-queue/questions.sqlite3')
def utc_now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn=sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=10000')
    conn.execute("""CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL UNIQUE, question TEXT NOT NULL, extra_context TEXT, raw_email_id TEXT, submitted_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', answer TEXT, answered_at TEXT, sent_at TEXT)""")
    conn.commit(); return conn
def enqueue_request(request):
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO questions (request_id,question,extra_context,raw_email_id,submitted_at,status) VALUES (?,?,?,?,?,'pending')", (request.request_id,request.question,request.extra_context,request.raw_email_id,utc_now()))
        row=conn.execute('SELECT id FROM questions WHERE request_id=?',(request.request_id,)).fetchone(); conn.commit(); return int(row['id'])
def answered_requests(limit=20):
    with connect() as conn: rows=conn.execute("SELECT * FROM questions WHERE status='answered' AND sent_at IS NULL ORDER BY id ASC LIMIT ?",(limit,)).fetchall()
    result=[]
    for row in rows:
        req=DTRequest(request_id=row['request_id'],question=row['question'],raw_email_id=row['raw_email_id'] or '',timestamp=row['request_id'],extra_context=row['extra_context'])
        result.append((int(row['id']),req,row['answer'] or ''))
    return result
def mark_sent(queue_id):
    with connect() as conn: conn.execute("UPDATE questions SET status='sent', sent_at=? WHERE id=?",(utc_now(),queue_id)); conn.commit()
