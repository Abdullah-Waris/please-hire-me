import json
import pytest
from hireme.discovery import posting,source_result,sweep_lists
from hireme.util import Blocked


def test_feed_destination_cannot_be_lookalike_or_private():
    for url in ['https://jobs.lever.co.attacker.invalid/acme/1','https://127.0.0.1/submit','https://attacker.invalid/jobs.lever.co/acme/1']:
        with pytest.raises(ValueError):posting(url,'Acme','Software Engineer','US','test')


def test_source_failure_keeps_candidates(store,job):
    source_result(store,'test',[job]);source_result(store,'test',error='timeout')
    assert store.db.execute('SELECT count(*) FROM jobs').fetchone()[0]==1
    assert store.db.execute('SELECT status FROM sources').fetchone()[0]=='error'


def test_list_feed_failure_records_error_without_watermark(store):
    class Net:
        context=None
        def json(self,*a,**k):raise TimeoutError()
        def fetch(self,*a,**k):raise TimeoutError()
    sweep_lists(store,Net())
    assert store.db.execute("SELECT count(*) FROM sources WHERE status='error'").fetchone()[0]==8
    assert not (store.root/'last_list_sweep.txt').exists()


def test_remote_shell_metacharacters_never_become_source_code(store):
    url='https://jobs.lever.co/acme/id-1'
    j=posting(url,"Acme'; print('no')",'Software Engineer','US','test')
    store.upsert_job(j)
    assert store.db.execute('SELECT company FROM jobs').fetchone()[0]==j['company']


def test_greenhouse_custom_link_uses_official_requisition():
    from hireme.discovery import probe
    class Net:
        def json(self,url):
            return {'jobs':[{'id':123,'absolute_url':'https://stripe.com/jobs/123',
                            'title':'Software Engineer Intern','location':{'name':'US'}}]}
    result=probe(Net(),'gh','stripe')
    assert result[0]['url']=='https://job-boards.greenhouse.io/stripe/jobs/123'
