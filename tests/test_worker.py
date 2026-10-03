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


def test_pause_during_application_stops_cycle_and_retains_count(store,job,package):
    class FakeBrowser:
        def __init__(self,s):self.s=s
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def apply(self,j,live=True):
            self.s.update_settings({'live_enabled':False})
            self.s.checkpoint()
    with pytest.raises(Blocked,match='paused'):
        cycle(store,Path('.'),discover=False,browser_factory=FakeBrowser)
    run=store.db.execute('SELECT * FROM runs').fetchone()
    assert run['status']=='paused' and json.loads(run['detail'])['attempts']==1
    assert not store.settings()['live_enabled']


def test_pause_then_resume_does_not_revive_old_cycle(store):
    store.run_generation=store.control_generation()
    store.update_settings({'live_enabled':False})
    store.update_settings({'live_enabled':True})
    with pytest.raises(Blocked,match='paused'):store.checkpoint()


def test_preparation_is_not_reported_as_confirmed_submission(store,job):
    class FakeBrowser:
        def __init__(self,s):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def apply(self,j,live=True):assert not live;return 'prepared'
    result=cycle(store,Path('.'),discover=False,live=False,limit=1,browser_factory=FakeBrowser)
    assert result['confirmed']==0 and result['prepared']==1 and result['shortfall']==0
    assert store.db.execute('SELECT submitted FROM runs').fetchone()[0]==0


def test_observed_cycle_has_hard_attempt_limit_and_job_selection(store,job):
    selected=[]
    for i in range(5):
        j={**job,'id':digest(i),'url':job['url']+str(i),'company':'Company '+str(i)}
        store.upsert_job(j)
        selected.append(j['id'])
    visited=[]
    class FakeBrowser:
        def __init__(self,s):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def apply(self,j,live=True):visited.append(j['id']);raise Blocked('missing_answers')
    result=cycle(store,Path('.'),discover=False,max_attempts=2,job_ids=set(selected[:2]),browser_factory=FakeBrowser)
    assert result['attempts']==2 and set(visited)==set(selected[:2]) and result['confirmed']==0
