"""Durable per-run reports; mail delivery never retries an application."""
from __future__ import annotations

import json
import uuid

from .gmail import GmailClient, owner_email
from .store import worker_lock
from .util import now


def queue_report(store, run_id):
    run = store.db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
    if not run or not run['finished']:
        raise ValueError('Only completed or stopped runs can be reported')
    email = owner_email(store)
    outcomes = []
    for e in store.db.execute("SELECT subject,detail FROM events WHERE kind='application_finished' AND timestamp>=? ORDER BY seq", (run['started'],)):
        detail = json.loads(e['detail'])
        if detail.get('run_id') != run_id:
            continue
        job = store.db.execute('SELECT company,title,url FROM jobs WHERE id=?', (e['subject'],)).fetchone()
        if job:
            outcomes.append(f"{job['company']} — {job['title']}: {detail['outcome']}"
                            + (f" ({detail['reason']})" if detail.get('reason') else '') + f"\n{job['url']}")
    detail = json.loads(run['detail']) if run['detail'].startswith('{') else {'reason': run['detail']}
    body = (f"Application batch {run_id}\nStarted: {run['started']}\nFinished: {run['finished']}\n"
            f"Status: {run['status']}\nMode: {detail.get('mode', 'live')}\n"
            f"Confirmed submissions: {run['submitted']}\nAttempts: {detail.get('attempts', 0)}\n\n"
            + ('\n\n'.join(outcomes) or 'No application outcomes recorded.'))
    if detail.get('reason'):
        body += '\n\nStopped because: ' + detail['reason']
    body += '\n\nOpen Application desk on the Pi: http://127.0.0.1:8766 (through Raspberry Pi Connect).\n'
    enabled = store.settings()['gmail_reports']
    with store.transaction():
        store.db.execute('INSERT OR IGNORE INTO report_outbox VALUES(?,?,?,?,?,?,?,0,NULL,NULL,NULL)',
                         (run_id, email, f"Application batch: {run['submitted']} confirmed — {run['status']}",
                          body, f'<{uuid.uuid4().hex}@please-hire-me.local>', 'pending' if enabled else 'disabled', now()))
    return run_id


def flush_reports(store, client_factory=GmailClient, limit=5):
    if not store.settings()['gmail_reports']:
        return {'sent': 0, 'enabled': False}
    sent = 0
    with worker_lock(store.root, 'reports'):
        # A process disappearing after send authorization may have delivered mail.
        store.db.execute("UPDATE report_outbox SET state='uncertain',last_error='Process stopped during mail send' WHERE state='sending'")
        rows = list(store.db.execute("SELECT * FROM report_outbox WHERE state='pending' ORDER BY created LIMIT ?", (limit,)))
        if not rows:
            return {'sent': 0, 'enabled': True}
        try:
            client = client_factory(store)
        except Exception as e:
            store.db.execute("UPDATE report_outbox SET last_error=? WHERE state='pending'", (getattr(e, 'reason', type(e).__name__),))
            return {'sent': 0, 'enabled': True, 'error': getattr(e, 'reason', type(e).__name__)}
        for row in rows:
            if row['recipient'] != client.email:
                store.db.execute("UPDATE report_outbox SET state='held',last_error='Owner email changed' WHERE id=?", (row['id'],))
                continue
            with store.transaction():
                store.db.execute("UPDATE report_outbox SET state='sending',attempts=attempts+1,last_error=NULL WHERE id=?", (row['id'],))
            try:
                receipt = client.send_report(row['subject'], row['body'], row['message_id'])
            except Exception as e:
                store.db.execute("UPDATE report_outbox SET state='uncertain',last_error=? WHERE id=?", (type(e).__name__, row['id']))
                store.event('batch_report_uncertain', row['id'], {})
                continue
            store.db.execute("UPDATE report_outbox SET state='sent',provider_id=?,sent=? WHERE id=?", (receipt, now(), row['id']))
            store.event('batch_report_sent', row['id'], {'provider_id': receipt})
            sent += 1
    return {'sent': sent, 'enabled': True}


def report_status(store):
    return [dict(r) for r in store.db.execute('SELECT id,state,created,sent,last_error FROM report_outbox ORDER BY created DESC LIMIT 30')]
