"""A disposable sample workspace; never touches the applicant's private data."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from .discovery import posting
from .store import Store
from .util import now


DEMO_READINESS = {
    'platform': 'Sample workspace', 'architecture': 'read-only', 'python': 'not connected',
    'browser_ready': True, 'provider': {'ready': False, 'message': 'No model connected in this preview.'},
    'missing': [], 'deployment': 'local', 'supported_platform': True,
}


def seed(store):
    store.update_settings({'onboarding_complete': True, 'live_enabled': False, 'timezone': 'America/New_York',
                           'target_per_day': 12, 'max_per_day': 20, 'target_per_cycle': 3,
                           'max_per_cycle': 5, 'provider': 'codex-cli'})
    entries = [
        ('Cedar Labs', 'Software Engineer Intern', 'New York, NY', 'confirmed', 92, ''),
        ('Meridian', 'New Grad Software Engineer', 'Remote (US)', 'confirmed', 87, ''),
        ('Atlas Research', 'Research Engineering Intern', 'Seattle, WA', 'blocked', 89, 'An application question needs your answer.'),
        ('Northstar', 'Software Engineer, Early Career', 'San Francisco, CA', 'discovered', 84, ''),
        ('Fieldwork', 'Machine Learning Intern', 'Remote (US)', 'discovered', 82, ''),
        ('Openwater', 'Developer Intern', 'New York, NY', 'discovered', 78, ''),
    ]
    stamp = now()
    for index, (company, title, location, status, score, reason) in enumerate(entries):
        # Names and requisitions are invented. Links are omitted from the frontend in demo mode.
        job = posting(f'https://jobs.lever.co/synthetic-preview/req-{index}', company, title, location,
                      'demo', 'Invented example opportunity for the read-only workspace preview.')
        store.upsert_job(job)
        store.db.execute('UPDATE jobs SET status=?,score=?,reason=? WHERE id=?', (status, score, reason, job['id']))
        if status == 'confirmed':
            store.db.execute('''INSERT INTO applications
                (id,job_id,company_key,state,package,hash,created,updated,attempted,confirmation)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (f'demo-application-{index}', job['id'], store.company(company), 'confirmed',
                 json.dumps({'answers': [{'field': {'label': 'Experience'},
                    'value': 'This is a synthetic answer in the sample workspace.',
                    'provenance': {'template_id': 'demo'}}]}), 'demo', stamp, stamp, stamp,
                 'Synthetic confirmation — no application was sent.'))
        if status == 'blocked':
            store.db.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,0)',
                             ('demo-question', job['id'], job['host'], 'Which engineering team interests you most?',
                              '["Infrastructure", "Product engineering", "Research"]', 'An exact personal answer is needed.'))
    started = (datetime.now(timezone.utc) - timedelta(minutes=18)).isoformat(timespec='seconds')
    store.db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?)',
                     ('demo-batch', started, stamp, 'finished', 2, json.dumps({
                         'confirmed': 2, 'attempts': 3, 'target': 3, 'shortfall': 1,
                         'outcomes': {'confirmed': 2, 'blocked': 1}, 'reason': 'Sample batch. No applications were sent.'})))


def run(repo: Path, port=8767):
    from .server import serve
    with TemporaryDirectory(prefix='hireme-preview-') as directory:
        root = Path(directory) / 'workspace'
        store = Store(root)
        try: seed(store)
        finally: store.close()
        serve(root, repo, port, demo=True)
