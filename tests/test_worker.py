from pathlib import Path
import json
import pytest
from hireme.worker import cycle
from hireme.util import Blocked,digest


def test_cycle_budget_is_code_not_prompt(store,job,package):
    for i in range(15):
        j={**job,'id':digest(i),'url':job['url']+str(i),'company':'Company '+str(i)};store.upsert_job(j)
    class FakeBrowser:
        def __init__(self,s):self.s=s
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def apply(self,j,live=True):
            p={**package,'job_id':j['id'],'url':j['url']}
            aid=self.s.prepare(j,p);self.s.begin_submit(aid);self.s.finish(aid,'confirmed')
            return 'confirmed'
    result=cycle(store,Path('.'),discover=False,limit=7,browser_factory=FakeBrowser)
    assert result['confirmed']==7
    assert store.db.execute("SELECT count(*) FROM applications WHERE state='confirmed'").fetchone()[0]==7


def test_unknown_outcome_distinct_from_blocked(store,job,package):
    class FakeBrowser:
        def __init__(self,s):self.s=s
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def apply(self,j,live=True):
            aid=self.s.prepare(j,package);self.s.begin_submit(aid);self.s.finish(aid,'unknown');raise Blocked('submission_unknown')
    cycle(store,Path('.'),discover=False,browser_factory=FakeBrowser)
    assert store.db.execute('SELECT status FROM jobs').fetchone()[0]=='unknown'
