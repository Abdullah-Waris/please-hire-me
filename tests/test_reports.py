from pathlib import Path
from hireme.reports import queue_report,flush_reports
from hireme.worker import cycle
from hireme.util import Blocked


def finished(store):
    store.db.execute("INSERT INTO runs VALUES('run-one','2026-01-01T00:00:00Z','2026-01-01T00:00:05Z','finished',0,'{}')")
    queue_report(store,'run-one')


def test_each_batch_has_one_durable_report_even_when_disabled(store):
    finished(store);queue_report(store,'run-one')
    assert store.db.execute('SELECT count(*) FROM report_outbox').fetchone()[0]==1
    assert store.db.execute('SELECT state FROM report_outbox').fetchone()[0]=='disabled'


def test_mail_setup_failure_keeps_report_pending_without_application_retry(store):
    store.update_settings({'gmail_reports':True});finished(store)
    def missing(s):raise Blocked('gmail_not_connected')
    assert flush_reports(store,missing)['sent']==0
    assert store.db.execute('SELECT state FROM report_outbox').fetchone()[0]=='pending'
    assert not store.db.execute('SELECT * FROM applications').fetchone()


def test_ambiguous_mail_send_is_not_automatically_repeated(store):
    store.update_settings({'gmail_reports':True});finished(store)
    class Client:
        email='test@candidate.invalid';calls=0
        def __init__(self,s):pass
        def send_report(self,*args):Client.calls+=1;raise TimeoutError()
    flush_reports(store,Client);flush_reports(store,Client)
    assert Client.calls==1 and store.db.execute('SELECT state FROM report_outbox').fetchone()[0]=='uncertain'


def test_paused_cycle_still_records_batch_summary(store):
    store.update_settings({'live_enabled':False})
    import pytest
    with pytest.raises(Blocked,match='paused'):cycle(store,Path('.'),discover=False)
    row=store.db.execute('SELECT * FROM report_outbox').fetchone()
    assert 'paused' in row['body'] and 'Confirmed submissions: 0' in row['body']
