"""Withdraw an optional upload from future work while retaining private evidence."""
from __future__ import annotations

import json

from .store import worker_lock
from .util import now


def withdraw_transcript(store):
    with worker_lock(store.root):
        with store.transaction():
            document=store.db.execute("SELECT * FROM documents WHERE kind='transcript'").fetchone()
            if not document: return {'removed': False, 'drafts_removed': 0}
            drafts=[]
            for app in store.db.execute("SELECT id,job_id,package FROM applications WHERE state='prepared'"):
                try: documents=json.loads(app['package']).get('documents',[])
                except (ValueError,TypeError,AttributeError): continue
                if isinstance(documents,list) and any(isinstance(doc,dict) and doc.get('kind')=='transcript' for doc in documents):
                    drafts.append((app['id'],app['job_id']))
            store.db.execute("DELETE FROM documents WHERE kind='transcript'")
            for aid,jid in drafts:
                store.db.execute("DELETE FROM applications WHERE id=? AND state='prepared'",(aid,))
                store.db.execute("UPDATE jobs SET status='discovered',reason='',updated=? WHERE id=? AND status='prepared'",(now(),jid))
            store.event('document_withdrawn','transcript',{'hash':document['hash'],'drafts_removed':len(drafts)})
    return {'removed': True, 'drafts_removed': len(drafts)}
