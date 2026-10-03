import csv
import io
import json
from datetime import datetime, timezone

import pytest

from hireme.discovery import posting
from hireme.ledger import export_csv, summary
from hireme.util import digest


def application(store, job, timestamp, state='confirmed'):
    store.db.execute('''INSERT INTO applications
        (id,job_id,company_key,state,package,hash,created,updated,attempted)
        VALUES(?,?,?,?,?,?,?,?,?)''',
        (digest(job['id']), job['id'], store.company(job['company']), state,
         '{"answers":[{"value":"Private candidate answer"}]}', 'fixture', timestamp, timestamp, timestamp))


@pytest.mark.parametrize(('day', 'timestamps', 'expected'), [
    # New York's spring clock change makes this local day 23 hours long.
    ('2026-03-08T12:00:00+00:00', ['2026-03-08T04:59:59+00:00', '2026-03-08T05:00:00+00:00',
                                 '2026-03-09T03:59:59+00:00', '2026-03-09T04:00:00+00:00'], 2),
    # The autumn clock change makes this local day 25 hours long.
    ('2026-11-01T12:00:00+00:00', ['2026-11-01T03:59:59+00:00', '2026-11-01T04:00:00+00:00',
                                 '2026-11-02T04:59:59+00:00', '2026-11-02T05:00:00+00:00'], 2),
])
def test_summary_counts_local_day_across_clock_changes(store, day, timestamps, expected):
    store.update_settings({'timezone': 'America/New_York'})
    for index, timestamp in enumerate(timestamps):
        job = posting(f'https://jobs.lever.co/clock/req-{index}', f'Clock {index}', 'Intern', 'US', 'fixture')
        store.upsert_job(job); application(store, job, timestamp)
    assert summary(store, datetime.fromisoformat(day))['submitted_today'] == expected


def test_summary_counts_complete_ledger_and_deduplicates_attention(store):
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    for index in range(510):
        job = posting(f'https://jobs.lever.co/large/req-{index}', f'Company {index}', 'Intern', 'US', 'fixture')
        store.upsert_job(job); application(store, job, stamp)
    assert len(store.snapshot()['jobs']) == 500
    result = summary(store)
    assert result['job_count'] == result['submitted_today'] == 510
    store.block(job['id'], 'unknown_fact')
    store.db.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,0)', ('question', job['id'], job['host'], 'Question', '[]', 'unknown_fact'))
    store.db.execute("UPDATE applications SET state='unknown' WHERE job_id=?", (job['id'],))
    store.db.execute('INSERT INTO employer_accounts VALUES(?,?,?,?,?)', ('account', 'https://jobs.lever.co', 'Company', 'uncertain', stamp))
    assert summary(store)['attention_count'] == 2


def test_export_complete_unicode_csv_without_answers_and_neutralizes_formulas(store):
    companies = ['Café Labs', '=HYPERLINK("https://example.invalid")', '  +SUM(1,1)', '@example', '\t=1+1']
    for index, company in enumerate(companies):
        job = posting(f'https://jobs.lever.co/export/req-{index}', company, 'Software, Research', 'New York\nRemote', 'fixture')
        store.upsert_job(job); application(store, job, '2026-01-01T00:00:00+00:00')
    data = export_csv(store)
    assert data.startswith(b'\xef\xbb\xbf') and b'Private candidate answer' not in data
    rows = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    assert len(rows) == 5
    by_company = {row['Company']: row for row in rows}
    assert 'Café Labs' in by_company
    assert all("'" + company in by_company for company in companies[1:])
    assert all(row['Fit score'] == '0' for row in rows)
    assert all(row['Role'] == 'Software, Research' for row in rows)
    assert all(row['Location'] == 'New York\nRemote' for row in rows)


def test_export_cli_keeps_existing_files(store, tmp_path, capsys):
    from hireme.cli import main
    path = tmp_path / 'ledger.csv'; path.write_text('keep this file')
    assert main(['--data-dir', str(store.root), 'export-ledger', str(path)]) == 2
    assert path.read_text() == 'keep this file'
    assert 'not overwritten' in capsys.readouterr().err
