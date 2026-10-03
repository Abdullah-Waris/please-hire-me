"""Read-only application summaries and spreadsheet-friendly ledger exports."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .presentation import QUIET_REASONS, job_display

EXPORT_COLUMNS = ('Company', 'Role', 'Location', 'Status', 'Fit score', 'Application URL',
                  'First discovered', 'Last updated', 'Attempted', 'Reason')



def summary(store, at=None):
    """Count the complete ledger, including records outside dashboard page limits."""
    local = (at or datetime.now(timezone.utc)).astimezone(ZoneInfo(store.settings()['timezone']))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    # Stored timestamps are UTC ISO strings with second resolution, like util.now().
    bounds = tuple(value.astimezone(timezone.utc).isoformat(timespec='seconds') for value in (start, end))
    counts = dict(store.db.execute('SELECT status,COUNT(*) FROM jobs GROUP BY status'))
    submitted = store.db.execute("""SELECT COUNT(*) FROM applications
        WHERE state='confirmed' AND attempted>=? AND attempted<?""", bounds).fetchone()[0]
    excluded = tuple(sorted(QUIET_REASONS))
    placeholders = ','.join('?' for _ in excluded)
    attention = store.db.execute(f"""SELECT COUNT(*) FROM (
        SELECT job_id FROM questions WHERE resolved=0
        UNION SELECT id FROM jobs WHERE status IN ('unknown','awaiting_verification')
            OR (status='blocked' AND TRIM(SUBSTR(reason,1,CASE WHEN INSTR(reason,':')>0
                THEN INSTR(reason,':')-1 ELSE LENGTH(reason) END)) NOT IN ({placeholders}))
        UNION SELECT job_id FROM applications WHERE state IN ('unknown','awaiting_verification')
    )""", excluded).fetchone()[0]
    accounts = store.db.execute("SELECT COUNT(*) FROM employer_accounts WHERE state='uncertain'").fetchone()[0]
    return {'job_count': sum(counts.values()), 'status_counts': counts, 'submitted_today': submitted,
            'attention_count': attention + accounts, 'local_date': local.date().isoformat()}


def spreadsheet_text(value):
    """Keep untrusted posting text from becoming a formula when opened in a spreadsheet."""
    text = str(value or '')
    if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
        return "'" + text
    return text


def export_csv(store):
    """Export job metadata only; personal answers and credentials stay out of this file."""
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(EXPORT_COLUMNS)
    for job in store.db.execute('''SELECT j.*,a.attempted FROM jobs j
        LEFT JOIN applications a ON a.job_id=j.id ORDER BY j.first_seen DESC,j.id'''):
        try: location = json.loads(job['payload']).get('location', '')
        except (ValueError, TypeError): location = ''
        writer.writerow([spreadsheet_text(value) for value in (
            job['company'], job['title'], location, job_display(dict(job))['status_label'],
            job['score'], job['url'], job['first_seen'], job['updated'], job['attempted'], job['reason'])])
    # UTF-8 BOM helps common spreadsheet apps recognize non-ASCII employer names.
    return output.getvalue().encode('utf-8-sig')
