from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DEFAULTS, REQUIRED, validate_fact, validate_settings
from .util import Blocked, atomic_json, company_key, digest, now, private_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS employer_accounts (id TEXT PRIMARY KEY, origin TEXT NOT NULL,
 company TEXT NOT NULL, state TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_requests (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, run_id TEXT NOT NULL, provider TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS model_requests_time ON model_requests(timestamp);
CREATE INDEX IF NOT EXISTS model_requests_run ON model_requests(run_id);
CREATE TABLE IF NOT EXISTS worker_control (id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL);
INSERT OR IGNORE INTO worker_control VALUES(1,0);
CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facts (key TEXT PRIMARY KEY, value TEXT NOT NULL, source TEXT NOT NULL,
 confirmed INTEGER NOT NULL, revision INTEGER NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS templates (id TEXT PRIMARY KEY, category TEXT NOT NULL, body TEXT NOT NULL, revision INTEGER NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS answers (id TEXT PRIMARY KEY, question TEXT NOT NULL, host TEXT NOT NULL,
 options TEXT NOT NULL, value TEXT NOT NULL, fact_key TEXT, revision INTEGER NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS writing_answers (id TEXT PRIMARY KEY, body TEXT NOT NULL, provenance TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS field_bindings (id TEXT PRIMARY KEY, host TEXT NOT NULL, label TEXT NOT NULL,
 options TEXT NOT NULL, fact_key TEXT, template_id TEXT, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS verification_challenges (application_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
 url TEXT NOT NULL, company TEXT NOT NULL, requested REAL NOT NULL, code_length INTEGER NOT NULL,
 state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS report_outbox (id TEXT PRIMARY KEY, recipient TEXT NOT NULL, subject TEXT NOT NULL,
 body TEXT NOT NULL, message_id TEXT NOT NULL UNIQUE, state TEXT NOT NULL, created TEXT NOT NULL,
 attempts INTEGER NOT NULL, provider_id TEXT, sent TEXT, last_error TEXT);
CREATE TABLE IF NOT EXISTS mail_consumptions (message_id TEXT PRIMARY KEY, challenge_id TEXT NOT NULL,
 consumed REAL NOT NULL);
CREATE TABLE IF NOT EXISTS materials (id TEXT PRIMARY KEY, hash TEXT NOT NULL, filename TEXT NOT NULL,
 original_name TEXT NOT NULL, media_type TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
 confirmed INTEGER NOT NULL, role TEXT NOT NULL, revision INTEGER NOT NULL, created TEXT NOT NULL,
 updated TEXT NOT NULL, UNIQUE(hash,kind));
CREATE TABLE IF NOT EXISTS documents (kind TEXT PRIMARY KEY, hash TEXT NOT NULL, filename TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS generated_documents (job_id TEXT NOT NULL, kind TEXT NOT NULL,
 hash TEXT NOT NULL, filename TEXT NOT NULL, fingerprint TEXT NOT NULL, provenance TEXT NOT NULL,
 created TEXT NOT NULL, PRIMARY KEY(job_id,kind));
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, company TEXT NOT NULL, company_key TEXT NOT NULL,
 title TEXT NOT NULL, url TEXT UNIQUE NOT NULL, host TEXT NOT NULL, source TEXT NOT NULL,
 payload TEXT NOT NULL, score INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'discovered',
 reason TEXT NOT NULL DEFAULT '', first_seen TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS applications (id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE,
 company_key TEXT NOT NULL, state TEXT NOT NULL, package TEXT NOT NULL, hash TEXT NOT NULL,
 created TEXT NOT NULL, updated TEXT NOT NULL, attempted TEXT, confirmation TEXT, screenshot TEXT);
CREATE TABLE IF NOT EXISTS questions (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, host TEXT NOT NULL,
 label TEXT NOT NULL, options TEXT NOT NULL, reason TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
 kind TEXT NOT NULL, subject TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, status TEXT NOT NULL, checked TEXT NOT NULL,
 error TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, started TEXT NOT NULL, finished TEXT,
 status TEXT NOT NULL, submitted INTEGER NOT NULL DEFAULT 0, detail TEXT NOT NULL DEFAULT '');
"""


class Store:
    def __init__(self, root: Path):
        self.root = private_dir(root)
        self.path = self.root / "ledger.sqlite3"
        if self.path.is_symlink():
            raise ValueError("Ledger must not be a symlink")
        self.db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)
        os.chmod(self.path, 0o600)
        self.db.execute("INSERT OR IGNORE INTO config VALUES (1, ?)", (json.dumps(DEFAULTS),))

    def close(self):
        self.db.close()

    @contextlib.contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def settings(self):
        return validate_settings(json.loads(self.db.execute("SELECT value FROM config").fetchone()[0]))

    def control_generation(self):
        return self.db.execute('SELECT generation FROM worker_control WHERE id=1').fetchone()[0]

    def checkpoint(self):
        generation=getattr(self,'run_generation',None)
        if generation is not None and (generation!=self.control_generation() or not self.settings()['live_enabled']):
            raise Blocked('paused')

    def reserve_model_request(self):
        with self.transaction():
            self.checkpoint()
            s=self.settings();rid=getattr(self,'active_run_id',None) or 'setup:'+datetime.now(ZoneInfo(s['timezone'])).date().isoformat()
            today=datetime.now(ZoneInfo(s['timezone'])).date()
            daily=sum(datetime.fromisoformat(r[0]).astimezone(ZoneInfo(s['timezone'])).date()==today for r in self.db.execute('SELECT timestamp FROM model_requests WHERE timestamp>=?',((datetime.now(timezone.utc)-timedelta(days=2)).isoformat(),)))
            cycle=self.db.execute('SELECT count(*) FROM model_requests WHERE run_id=?',(rid,)).fetchone()[0]
            if daily>=s['max_model_requests_per_day'] or cycle>=s['max_model_requests_per_cycle']:raise Blocked('model_budget_exhausted','Wait for the next batch/day or change your request limits')
            self.db.execute('INSERT INTO model_requests(timestamp,run_id,provider) VALUES(?,?,?)',(now(),rid,s['provider']))

    def event(self, kind, subject, detail):
        self.db.execute("INSERT INTO events(timestamp,kind,subject,detail) VALUES(?,?,?,?)",
                        (now(), kind, str(subject), json.dumps(detail, ensure_ascii=False)))

    def update_settings(self, changes):
        with self.transaction():
            s = validate_settings(changes, self.settings())
            if s["live_enabled"] and (not s["onboarding_complete"] or self.missing_setup()):
                raise ValueError("Finish confirmed onboarding before enabling submissions")
            if changes.get("live_enabled") is False:
                self.db.execute("UPDATE worker_control SET generation=generation+1 WHERE id=1")
                self.event("pause_requested", "worker", {})
            self.db.execute("UPDATE config SET value=? WHERE id=1", (json.dumps(s),))
            self.event("settings_updated", "config", changes)
        self.export_config()
        return s

    def facts(self, confirmed=True):
        rows = self.db.execute("SELECT * FROM facts" + (" WHERE confirmed=1" if confirmed else ""))
        return {r["key"]: dict(r) for r in rows}

    def put_facts(self, values, source="user", confirmed=True):
        # A dashboard submission is an explicit user confirmation, not model approval.
        values = {k: validate_fact(k, v) for k, v in values.items() if v is not None and v != ""}
        with self.transaction():
            old = self.facts(False)
            if "email" in old and old["email"]["confirmed"] and "email" in values and values["email"] != old["email"]["value"]:
                if self.db.execute("SELECT 1 FROM applications LIMIT 1").fetchone():
                    raise ValueError("Applicant identity cannot change after application history exists")
            for key, value in values.items():
                self.db.execute("""INSERT INTO facts VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                  value=excluded.value, source=excluded.source, confirmed=excluded.confirmed,
                  revision=facts.revision+1, updated=excluded.updated""", (key,value,source,int(confirmed),1,now()))
            self.event("facts_confirmed" if confirmed else "facts_proposed", "profile", sorted(values))
            # Prepared packages are invalidated by any profile change.
            self.db.execute("DELETE FROM applications WHERE state='prepared'")
        self.export_config()

    def export_config(self):
        atomic_json(self.root / "config" / "profile.json", {k:v["value"] for k,v in self.facts().items()})
        atomic_json(self.root / "config" / "settings.json", self.settings())
        atomic_json(self.root / "config" / "answers.json", [dict(x) for x in self.db.execute("SELECT * FROM answers")])

    def missing_setup(self):
        missing = sorted(REQUIRED - self.facts().keys())
        if not self.db.execute("SELECT 1 FROM documents WHERE kind='resume'").fetchone():
            missing.append("resume")
        f = self.facts()
        if all(k in f for k in ("earliest_start", "latest_start")) and f["earliest_start"]["value"] > f["latest_start"]["value"]:
            missing.append("valid start window")
        if self.db.execute("SELECT 1 FROM questions WHERE reason='legacy_history_review' AND resolved=0").fetchone():
            missing.append("legacy history review")
        return missing

    @staticmethod
    def question_key(host, label, options):
        return digest([host.lower(), " ".join(label.casefold().split()), options])

    def ask(self, job_id, host, label, options, reason="missing_fact"):
        key = self.question_key(host, label, options)
        self.db.execute("INSERT INTO questions VALUES(?,?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET job_id=excluded.job_id,reason=excluded.reason,resolved=0",
                        (key, job_id, host, label, json.dumps(options), reason))
        return key

    def answer_question(self, qid, value, fact_key=None):
        q = self.db.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
        if not q:
            raise ValueError("Question does not exist")
        if not isinstance(value,str) or not value.strip() or len(value)>12000:
            raise ValueError("A nonempty answer is required")
        options = json.loads(q["options"])
        if options and value not in options:
            raise ValueError("Choose an exact option")
        if fact_key:
            f = self.facts().get(fact_key)
            if not f or f["value"] != value:
                raise ValueError("Answer must equal the confirmed fact")
        with self.transaction():
            self.db.execute("""INSERT INTO answers VALUES(?,?,?,?,?,?,1,?) ON CONFLICT(id) DO UPDATE SET
                value=excluded.value,fact_key=excluded.fact_key,revision=answers.revision+1,updated=excluded.updated""",
                (qid,q["label"],q["host"],q["options"],value,fact_key,now()))
            self.db.execute("UPDATE questions SET resolved=1 WHERE id=?", (qid,))
            self.db.execute("""UPDATE jobs SET status='discovered',reason='',updated=? WHERE status='blocked' AND id IN
                (SELECT job_id FROM questions WHERE id=?)""", (now(),qid))
            self.event("answer_saved",qid,{"fact_key":fact_key})
        self.export_config()

    def put_template(self, category, body, tid=None):
        if category not in ("motivation", "project", "experience") or not isinstance(body,str) or not 20<=len(body)<=12000:
            raise ValueError("Choose a template category and 20–12000 characters of confirmed text")
        tid=tid or uuid.uuid4().hex
        self.db.execute("INSERT INTO templates VALUES(?,?,?,1,?) ON CONFLICT(id) DO UPDATE SET category=excluded.category,body=excluded.body,revision=templates.revision+1,updated=excluded.updated",(tid,category,body,now()))
        self.event("template_confirmed",tid,{"category":category})
        return tid

    def templates(self):
        return [dict(x) for x in self.db.execute("SELECT * FROM templates")]

    def saved_answer(self, host, label, options):
        qid = self.question_key(host,label,options)
        r = self.db.execute("SELECT * FROM answers WHERE id=?",(qid,)).fetchone()
        if not r and '|' in host:
            # User-linked universal facts can be reused for identical wording/options at the same ATS.
            universal={'full_name','first_name','last_name','email','phone','location','street','city','state','postal_code','country','linkedin','github','website','school','high_school','major','graduation','gpa','work_authorized_us','needs_sponsorship','citizenship','us_person','unrestricted_authorization','race','gender','veteran','disability','professional_years'}
            for candidate in self.db.execute("SELECT * FROM answers WHERE question=? AND options=? AND fact_key IS NOT NULL",(label,json.dumps(options))):
                if candidate['host'].split('|',1)[0]==host.split('|',1)[0] and candidate['fact_key'] in universal:
                    r=candidate;break
        return dict(r) if r else None

    def writing_answer(self, host, label, options):
        row=self.db.execute('SELECT * FROM writing_answers WHERE id=?',(self.question_key(host,label,options),)).fetchone()
        return {'value':row['body'],'provenance':json.loads(row['provenance'])} if row else None

    def save_writing_answer(self, host, label, options, answer):
        self.db.execute('INSERT OR REPLACE INTO writing_answers VALUES(?,?,?)',
                        (self.question_key(host,label,options),answer['value'],json.dumps(answer['provenance'])))

    def field_binding(self, host, label, options):
        row=self.db.execute('SELECT * FROM field_bindings WHERE id=?',(self.question_key(host,label,options),)).fetchone()
        return dict(row) if row else None

    def bind_field(self, host, label, options, fact_key=None, template_id=None):
        if bool(fact_key)==bool(template_id):raise ValueError('Choose one supported source')
        if fact_key and fact_key not in self.facts():raise ValueError('Unconfirmed fact')
        if template_id and not any(t['id']==template_id for t in self.templates()):raise ValueError('Unknown template')
        self.db.execute('INSERT OR REPLACE INTO field_bindings VALUES(?,?,?,?,?,?,?)',
                        (self.question_key(host,label,options),host,label,json.dumps(options),fact_key,template_id,now()))

    def resolve_known_question(self, host, label):
        self.db.execute('UPDATE questions SET resolved=1 WHERE host=? AND label=? AND reason!=?',
                        (host,label,'legacy_history_review'))

    def upsert_job(self, job):
        key = job["id"]
        ck = self.company(job["company"])
        self.db.execute("""INSERT INTO jobs(id,company,company_key,title,url,host,source,payload,first_seen,updated)
         VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET payload=excluded.payload,updated=excluded.updated""",
          (key,job["company"],ck,job["title"],job["url"],job["host"],job["source"],json.dumps(job),now(),now()))

    def company(self, name):
        s=self.settings(); n=company_key(name)
        aliases={company_key(k):company_key(v) for k,v in s["company_aliases"].items()}
        return aliases.get(n,n)

    def block(self, jid, reason, detail=""):
        self.db.execute("UPDATE jobs SET status='blocked',reason=?,updated=? WHERE id=?",(reason + (": " + detail if detail else ""),now(),jid))
        self.event("blocked",jid,{"reason":reason,"detail":detail})

    def _check_budget(self, job, s):
        ck=self.company(job["company"])
        if ck in {self.company(x) for x in s["skip_companies"]+s["interview_companies"]}:
            raise Blocked("company_blocked")
        active = list(self.db.execute("SELECT * FROM applications WHERE company_key=? AND state IN ('submitting','unknown','confirmed','awaiting_verification')",(ck,)))
        if any(r["state"]=="awaiting_verification" for r in active):
            raise Blocked("company_verification_pending","Complete the earlier application verification first")
        if any(r["state"] in ("submitting","unknown") for r in active):
            raise Blocked("company_uncertain","Reconcile the earlier attempt first")
        if len(active)>=s["max_per_company"]:
            raise Blocked("company_limit")
        local_day=datetime.now(ZoneInfo(s["timezone"])).date()
        all_active=list(self.db.execute("SELECT * FROM applications WHERE state IN ('submitting','unknown','confirmed','awaiting_verification')"))
        daily=[r for r in all_active if datetime.fromisoformat(r["attempted"] or r["created"]).astimezone(ZoneInfo(s["timezone"])).date()==local_day]
        if len(daily)>=s["max_per_day"]:
            raise Blocked("daily_limit")
        if any(r["company_key"]==ck for r in daily):
            raise Blocked("company_same_day")
        cutoff=datetime.now(timezone.utc)-timedelta(days=s["company_cooldown_days"])
        if any(datetime.fromisoformat(r["attempted"] or r["created"])>cutoff for r in active):
            raise Blocked("company_cooldown")

    def prepare(self, job, package):
        from .answers import validate_package
        validate_package(self,job,package)
        with self.transaction():
            s=self.settings()
            self._check_budget(job,s)
            prev=self.db.execute("SELECT state FROM applications WHERE job_id=?",(job["id"],)).fetchone()
            if prev and prev[0] != "prepared":
                raise Blocked("duplicate_or_uncertain")
            aid=digest([job["id"], package])
            self.db.execute("DELETE FROM applications WHERE job_id=? AND state='prepared'",(job["id"],))
            self.db.execute("INSERT INTO applications(id,job_id,company_key,state,package,hash,created,updated) VALUES(?,?,?,'prepared',?,?,?,?)",
                (aid,job["id"],self.company(job["company"]),json.dumps(package),digest(package),now(),now()))
            self.event("prepared",aid,{"package_hash":digest(package)})
        return aid

    def begin_submit(self, aid):
        from .answers import validate_package
        from .policy import eligible
        with self.transaction():
            self.checkpoint()
            app=self.db.execute("SELECT * FROM applications WHERE id=?",(aid,)).fetchone()
            if not app or app["state"]!="prepared":
                raise Blocked("invalid_transition")
            s=self.settings()
            if not s["live_enabled"] or not s["onboarding_complete"] or self.missing_setup():
                raise Blocked("not_ready")
            job=json.loads(self.db.execute("SELECT payload FROM jobs WHERE id=?",(app["job_id"],)).fetchone()[0])
            package=json.loads(app["package"])
            if digest(package)!=app["hash"]:
                raise Blocked("package_tampered")
            eligible(job,s,self.facts())
            validate_package(self,job,package)
            self._check_budget(job,s)
            self.db.execute("UPDATE applications SET state='submitting',attempted=?,updated=? WHERE id=?",(now(),now(),aid))
            self.event("submit_intent",aid,{"hash":app["hash"]})
        return package

    def begin_verification(self,aid):
        with self.transaction():
            self.checkpoint()
            if not self.settings()['live_enabled']:raise Blocked('paused')
            app=self.db.execute('SELECT state FROM applications WHERE id=?',(aid,)).fetchone()
            challenge=self.db.execute('SELECT * FROM verification_challenges WHERE application_id=?',(aid,)).fetchone()
            if not app or app[0]!='awaiting_verification' or not challenge or challenge['state']!='pending' or challenge['attempts']>=1:
                raise Blocked('verification_not_ready')
            self.db.execute("UPDATE applications SET state='submitting',updated=? WHERE id=?",(now(),aid))
            self.db.execute("UPDATE verification_challenges SET state='verifying',attempts=attempts+1 WHERE application_id=?",(aid,))
            self.event('verification_intent',aid,{})

    def finish(self, aid, state, confirmation="", screenshot=""):
        if state not in ("confirmed","unknown","awaiting_verification"):
            raise ValueError("Invalid outcome")
        with self.transaction():
            r=self.db.execute("SELECT state,job_id FROM applications WHERE id=?",(aid,)).fetchone()
            if not r or r[0]!="submitting":
                raise Blocked("invalid_transition")
            self.db.execute("UPDATE applications SET state=?,updated=?,confirmation=?,screenshot=? WHERE id=?",
                            (state,now(),confirmation[-4000:],screenshot,aid))
            self.db.execute("UPDATE jobs SET status=?,reason=?,updated=? WHERE id=?",
                            (state,"" if state=="confirmed" else "Email verification required; application not yet submitted" if state=="awaiting_verification" else "Submission outcome needs reconciliation",now(),r[1]))
            self.db.execute("UPDATE verification_challenges SET state=? WHERE application_id=?",('complete' if state=='confirmed' else 'held' if state=='unknown' else 'pending',aid))
            self.event(state,aid,{"confirmation":confirmation[-4000:],"screenshot":screenshot})

    def recover(self):
        with self.transaction():
            self.db.execute("UPDATE employer_accounts SET state='uncertain',updated=? WHERE state='creating'",(now(),))
            rows=list(self.db.execute("SELECT id,job_id FROM applications WHERE state='submitting'"))
            for r in rows:
                self.db.execute("UPDATE applications SET state='unknown',updated=? WHERE id=?",(now(),r[0]))
                self.db.execute("UPDATE jobs SET status='unknown',reason='Worker stopped after submit intent',updated=? WHERE id=?",(now(),r[1]))
                self.db.execute("UPDATE verification_challenges SET state='held' WHERE application_id=?",(r[0],))
                self.event("crash_recovered",r[0],{"state":"unknown"})
            self.db.execute("UPDATE runs SET status='interrupted',finished=? WHERE status='running'",(now(),))

    def reconcile(self, aid, submitted: bool, note: str):
        if not isinstance(note,str) or len(note.strip())<10:
            raise ValueError("Describe how you verified the outcome")
        with self.transaction():
            r=self.db.execute("SELECT state,job_id FROM applications WHERE id=?",(aid,)).fetchone()
            if not r or r[0] not in ("unknown","awaiting_verification"):
                raise ValueError("Only uncertain or verification-pending submissions can be reconciled")
            state="confirmed" if submitted else "not_submitted"
            self.db.execute("UPDATE applications SET state=?,confirmation=?,updated=? WHERE id=?",(state,note,now(),aid))
            self.db.execute("UPDATE jobs SET status=?,reason=?,updated=? WHERE id=?",(state,note,now(),r[1]))
            self.event("human_reconciliation",aid,{"submitted":submitted,"note":note})
        # A not-submitted outcome is deliberately not retried automatically.

    def snapshot(self,material_offset=0):
        if type(material_offset) is not int or not 0<=material_offset<=1000000:raise ValueError("Invalid material page")
        def rows(q): return [dict(x) for x in self.db.execute(q)]
        return {"settings":self.settings(),"templates":self.templates(),"facts":self.facts(False),"missing_setup":self.missing_setup(),
                "jobs":rows("SELECT * FROM jobs ORDER BY score DESC,first_seen DESC LIMIT 500"),
                "applications":rows("SELECT * FROM applications ORDER BY created DESC LIMIT 500"),
                "questions":rows("SELECT * FROM questions WHERE resolved=0 ORDER BY rowid"),
                "runs":rows("SELECT * FROM runs ORDER BY started DESC LIMIT 30"),
                "sources":rows("SELECT * FROM sources ORDER BY checked DESC LIMIT 100"),
                "documents":rows("SELECT * FROM documents"),"materials":[dict(r) for r in self.db.execute("SELECT * FROM materials ORDER BY created DESC,id DESC LIMIT 20 OFFSET ?",(material_offset,))],"material_count":self.db.execute("SELECT count(*) FROM materials").fetchone()[0],"material_offset":material_offset}


@contextlib.contextmanager
def worker_lock(root: Path, name="worker"):
    private_dir(root)
    path=root / (name + ".lock")
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise Blocked("worker_busy")
        yield
    finally:
        os.close(fd)
