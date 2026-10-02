from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .browser import Browser
from .discovery import sweep_boards,sweep_lists,sweep_portals
from .policy import eligible
from .util import Blocked,now
from .store import worker_lock


def cycle(store,repo,discover=True,live=True,limit=None,browser_factory=Browser):
    with worker_lock(store.root):
        store.recover()
        rid=uuid.uuid4().hex; s=store.settings(); count=0; reasons={}; start=time.monotonic()
        store.db.execute("INSERT INTO runs(id,started,status) VALUES(?,?,'running')",(rid,now()))
        try:
            if store.missing_setup() or not s['onboarding_complete']:
                raise Blocked('setup_incomplete',', '.join(store.missing_setup()))
            if live and not s['live_enabled']:raise Blocked('paused')
            if discover:
                sweep_lists(store); sweep_portals(store); sweep_boards(store,repo)
            rows=list(store.db.execute("SELECT * FROM jobs WHERE status IN ('discovered','blocked','prepared') ORDER BY score DESC,first_seen DESC"))
            ranked=[]
            for row in rows:
                job=json.loads(row['payload'])
                try:
                    score,evidence=eligible(job,s,store.facts())
                    store.db.execute('UPDATE jobs SET score=? WHERE id=?',(score,job['id']))
                    ranked.append((score,job))
                except Blocked as e:
                    store.block(job['id'],e.reason,e.detail);reasons[e.reason]=reasons.get(e.reason,0)+1
            today=datetime.now(ZoneInfo(s['timezone'])).date()
            sent_today=sum(1 for r in store.db.execute("SELECT attempted FROM applications WHERE state='confirmed'")
                          if r[0] and datetime.fromisoformat(r[0]).astimezone(ZoneInfo(s['timezone'])).date()==today)
            # Seven normally; use spare slots when behind the daily trajectory. Never exceed ten.
            expected=max(s['target_per_cycle'],(s['target_per_day']*datetime.now(ZoneInfo(s['timezone'])).hour)//24-sent_today)
            target=min(s['max_per_cycle'],max(s['target_per_cycle'],expected),s['max_per_day']-sent_today)
            if limit is not None:target=min(target,limit)
            if ranked and target>0:
                with worker_lock(store.root,'browser'):
                    with browser_factory(store) as browser:
                        for _,job in sorted(ranked,key=lambda x:x[0],reverse=True):
                            if count>=target or time.monotonic()-start>s['cycle_timeout_seconds']:break
                            if not store.settings()['live_enabled'] and live:raise Blocked('paused')
                            try:
                                outcome=browser.apply(job,live=live)
                                store.db.execute('UPDATE jobs SET status=? WHERE id=?',(outcome,job['id']))
                                if outcome=='confirmed' or not live and outcome=='prepared':count+=1
                            except Blocked as e:
                                reasons[e.reason]=reasons.get(e.reason,0)+1
                                # Unknown outcomes must retain their distinct state.
                                state=store.db.execute('SELECT state FROM applications WHERE job_id=?',(job['id'],)).fetchone()
                                if not state or state[0] not in ('unknown','submitting'):store.block(job['id'],e.reason,e.detail)
                            except Exception as e:
                                reasons['browser_error']=reasons.get('browser_error',0)+1
                                store.block(job['id'],'browser_error',type(e).__name__)
            detail=json.dumps({'target':target,'confirmed':count,'shortfall':max(0,target-count),'reasons':reasons,'mode':'live' if live else 'prepare'})
            store.db.execute("UPDATE runs SET finished=?,status='finished',submitted=?,detail=? WHERE id=?",(now(),count if live else 0,detail,rid))
            return json.loads(detail)
        except Exception as e:
            store.recover()
            store.db.execute("UPDATE runs SET finished=?,status='blocked',detail=? WHERE id=?",(now(),str(e),rid))
            raise


def daemon(store,repo):
    # Only one scheduling loop per shared identity ledger, including across clones.
    with worker_lock(store.root,'scheduler'):
        while True:
            try:cycle(store,repo)
            except Blocked as e:store.event('cycle_blocked','scheduler',{'reason':e.reason,'detail':e.detail})
            except Exception as e:store.event('cycle_failed','scheduler',{'type':type(e).__name__})
            seconds=store.settings()['schedule_hours']*3600
            for _ in range(seconds):time.sleep(1)
