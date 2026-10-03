import pytest
from reportlab.pdfgen import canvas

from hireme.onboarding import import_resume
from hireme.util import Blocked,digest


def resume_pdf(path,lines):
    pdf=canvas.Canvas(str(path))
    for index,line in enumerate(lines):pdf.drawString(72,720-index*20,line)
    pdf.save();return path


def test_exact_confirmed_resume_values_keep_revisions_and_identical_import_keeps_drafts(store,job,package,tmp_path):
    path=resume_pdf(tmp_path/'resume.pdf',['Test Person','Synthetic candidate resume.'])
    before=store.facts()
    import_resume(store,path)
    assert store.facts()==before
    document=dict(store.db.execute("SELECT * FROM documents WHERE kind='resume'").fetchone())
    aid=store.prepare(job,{**package,'documents':[{**document,'field':package['documents'][0]['field']}]})
    draft=dict(store.db.execute('SELECT * FROM applications WHERE id=?',(aid,)).fetchone())
    import_resume(store,path)
    assert store.facts()==before
    assert dict(store.db.execute('SELECT * FROM applications WHERE id=?',(aid,)).fetchone())==draft


def test_changed_name_requires_confirmation_and_identity_rejection_does_not_select_another_pdf(store,job,package,tmp_path):
    aid=store.prepare(job,package);store.begin_submit(aid);store.finish(aid,'confirmed')
    document=dict(store.db.execute("SELECT * FROM documents WHERE kind='resume'").fetchone());before=store.facts(False)
    rejected=resume_pdf(tmp_path/'another-person.pdf',['Another Person','another@candidate.invalid'])
    with pytest.raises(ValueError,match='identity cannot change'):import_resume(store,rejected)
    assert dict(store.db.execute("SELECT * FROM documents WHERE kind='resume'").fetchone())==document
    assert store.facts(False)==before
    accepted=resume_pdf(tmp_path/'changed-name.pdf',['Changed Person','test@candidate.invalid'])
    import_resume(store,accepted)
    assert store.facts(False)['full_name']['value']=='Changed Person'
    assert not store.facts(False)['full_name']['confirmed']
    assert store.facts()['email']==before['email']
    assert store.db.execute('SELECT state FROM applications WHERE id=?',(aid,)).fetchone()[0]=='confirmed'


def test_document_storage_failure_rolls_back_fact_proposals_and_selected_pdf(store,job,package,tmp_path,monkeypatch):
    aid=store.prepare(job,package)
    store.db.execute("UPDATE jobs SET status='prepared' WHERE id=?",(job['id'],))
    before=store.facts(False);document=dict(store.db.execute("SELECT * FROM documents WHERE kind='resume'").fetchone())
    profile=(store.root/'config'/'profile.json').read_bytes()
    path=resume_pdf(tmp_path/'new.pdf',['Changed Person','Synthetic applicant.'])
    def fail(*args):raise OSError('Synthetic document storage failure')
    monkeypatch.setattr('hireme.onboarding.write_private_blob',fail)
    with pytest.raises(OSError):import_resume(store,path)
    assert store.facts(False)==before and (store.root/'config'/'profile.json').read_bytes()==profile
    assert dict(store.db.execute("SELECT * FROM documents WHERE kind='resume'").fetchone())==document
    assert store.db.execute('SELECT state FROM applications WHERE id=?',(aid,)).fetchone()[0]=='prepared'
    assert store.db.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]=='prepared'


def test_nested_fact_transaction_rolls_back_without_export_and_cannot_reserve_model_calls(store):
    before=store.facts(False);profile=(store.root/'config'/'profile.json').read_bytes()
    with pytest.raises(ValueError):
        with store.transaction():
            store.put_facts({'full_name':'Changed Person'})
            with pytest.raises(Blocked,match='model_request_transaction'):store.reserve_model_request()
            raise ValueError('Synthetic outer rollback')
    assert store.facts(False)==before and (store.root/'config'/'profile.json').read_bytes()==profile
    assert not store.db.execute('SELECT * FROM model_requests').fetchone()


def test_replacing_a_transcript_clears_only_its_draft_and_resets_its_prepared_label(store,job,package,tmp_path):
    transcript=resume_pdf(tmp_path/'first-transcript.pdf',['Synthetic transcript: original.'])
    import_resume(store,transcript,'transcript')
    document=dict(store.db.execute("SELECT * FROM documents WHERE kind='transcript'").fetchone())
    aid=store.prepare(job,{**package,'documents':[*package['documents'],{**document,'field':package['documents'][0]['field']}]})
    store.db.execute("UPDATE jobs SET status='prepared' WHERE id=?",(job['id'],))
    second={**job,'id':digest('without-transcript'),'url':job['url']+'-second','company':'Other Company'}
    store.upsert_job(second)
    unrelated=store.prepare(second,{**package,'job_id':second['id'],'url':second['url']})
    replacement=resume_pdf(tmp_path/'second-transcript.pdf',['Synthetic transcript: updated.'])
    import_resume(store,replacement,'transcript')
    assert not store.db.execute('SELECT 1 FROM applications WHERE id=?',(aid,)).fetchone()
    assert store.db.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]=='discovered'
    assert store.db.execute('SELECT state FROM applications WHERE id=?',(unrelated,)).fetchone()[0]=='prepared'


def test_fact_changes_clear_prepared_labels_but_preserve_manual_holds(store,job,package):
    aid=store.prepare(job,package)
    store.db.execute("UPDATE jobs SET status='prepared' WHERE id=?",(job['id'],))
    store.put_facts({'phone':'5557654321'})
    assert not store.db.execute('SELECT 1 FROM applications WHERE id=?',(aid,)).fetchone()
    assert store.db.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]=='discovered'
    fresh={**package,'facts_hash':digest(store.facts())}
    store.prepare(job,fresh);store.block(job['id'],'company_blocked')
    store.put_facts({'phone':'5557654322'})
    assert store.db.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]=='blocked'
