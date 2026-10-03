import io
import zipfile
import pytest
from hireme.materials import extract_text,import_material,review_material,writing_context,writing_context_hash
from hireme.answers import resolve
from hireme.util import Blocked


def office(parts):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        for name,text in parts.items():z.writestr(name,text)
    return b.getvalue()


def test_docx_preserves_paragraphs_without_executing_embedded_content():
    data=office({'word/document.xml':'<document><p><r><t>I built </t></r><r><t>a service.</t></r></p><p><r><t>I tested it.</t></r></p></document>','word/embeddings/script.bin':'dangerous code'})
    assert extract_text(data,'.docx')=='I built a service.\n\nI tested it.'


def test_pptx_uses_presentation_order():
    data=office({'ppt/presentation.xml':'<p xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sldId r:id="b"/><sldId r:id="a"/></p>',
                'ppt/_rels/presentation.xml.rels':'<rels><r Id="a" Target="slides/slide1.xml"/><r Id="b" Target="slides/slide2.xml"/></rels>',
                'ppt/slides/slide1.xml':'<slide><p><t>First file</t></p></slide>',
                'ppt/slides/slide2.xml':'<slide><p><t>First presented</t></p></slide>'})
    assert extract_text(data,'.pptx')=='First presented\n\nFirst file'


@pytest.mark.parametrize('data,suffix',[(b'\xff','.txt'),(b'\x00bad','.txt'),(b'not an archive','.docx'),(b'bad','.exe'),(office({'word/document.xml':'<!DOCTYPE x [<!ENTITY e "expand">]><x>&e;</x>'}),'.docx')])
def test_unsafe_or_unreadable_sources_are_rejected(data,suffix):
    with pytest.raises(ValueError):extract_text(data,suffix)


def test_import_is_private_unapproved_and_idempotent(store):
    facts=store.facts();body=b'I built a Python service that supports my team.'
    source=import_material(store,body,'my sample.txt','writing_sample')
    assert source['confirmed']==0 and store.facts()==facts and not store.templates()
    assert import_material(store,body,'renamed.txt','writing_sample')['id']==source['id']
    assert (store.root/'materials'/source['filename']).stat().st_mode&0o777==0o600
    assert not writing_context(store)['style_samples']


def test_style_and_reference_claims_never_become_factual_sources(store):
    facts=store.facts()
    source=import_material(store,b'I invented a spacecraft and won every award.','example.txt','cover_letter')
    review_material(store,source['id'],source['text'],'style',True)
    assert not store.templates()
    assert writing_context(store)['style_samples'][0]['text']==source['text']
    review_material(store,source['id'],source['text'],'reference',True)
    assert not store.templates() and writing_context(store)['reference_context']
    assert store.facts()==facts


def test_personal_sources_require_review_and_revocation_invalidates_writing(store,job):
    source=import_material(store,b'I built a Python service that supports my team.','work.txt','context')
    review_material(store,source['id'],source['text'],'personal',True)
    store.update_settings({'tailored_writing':True})
    class Model:
        def draft_answer(self,label,choices,context,maxlength):return {'answer':'I enjoy building Python services for teams.','sentence_ids':[choices[0]['id']]}
    field={'label':'Why do you want to join?','type':'textarea','required':True,'options':[]}
    assert resolve(store,job['host'],field,Model(),job)['value']
    review_material(store,source['id'],source['text'],'personal',False)
    with pytest.raises(Blocked):resolve(store,job['host'],field,context=job)
    assert not store.templates()


def test_source_changes_invalidate_posting_context_hash(store,job):
    before=writing_context_hash(store,job)
    source=import_material(store,b'I prefer concise letters grounded in concrete work.','voice.txt','cover_letter')
    assert writing_context_hash(store,job)==before
    review_material(store,source['id'],source['text'],'style',True)
    assert writing_context_hash(store,job)!=before


def test_large_style_library_has_bounded_model_context(store):
    for i in range(5):
        source=import_material(store,((str(i)+' style ') * 1300).encode(),'example.txt','cover_letter')
        review_material(store,source['id'],source['text'],'style',True)
    assert sum(len(s['text']) for s in writing_context(store)['style_samples'])<=12000


def test_source_library_snapshot_is_paginated_without_losing_context(store):
    from hireme.materials import import_material
    for i in range(25):import_material(store,f'This is factual source number {i} with enough text for review.'.encode(),f'source-{i}.txt','context')
    first=store.snapshot();second=store.snapshot(20)
    assert first['material_count']==25 and len(first['materials'])==20 and len(second['materials'])==5
    assert not {m['id'] for m in first['materials']} & {m['id'] for m in second['materials']}


@pytest.mark.parametrize('role', ['personal', 'style', 'reference'])
def test_review_changes_discard_only_unattempted_drafts(store, job, package, role):
    source = import_material(store, b'I built a Python service that supports my team.', 'work.txt', 'context')
    review_material(store, source['id'], source['text'], role, True)
    recorded = store.prepare(job, package)
    store.begin_submit(recorded); store.finish(recorded, 'unknown')
    from hireme.util import digest
    second = {**job, 'id': digest('source-change-draft'), 'url': job['url'] + '-draft', 'company': 'Other Synthetic Employer'}
    store.upsert_job(second)
    draft = store.prepare(second, {**package, 'job_id': second['id'], 'url': second['url']})
    result = review_material(store, source['id'], source['text'], role, False)
    assert result == {'changed': True, 'drafts_removed': 1}
    assert not store.db.execute('SELECT * FROM applications WHERE id=?', (draft,)).fetchone()
    assert store.db.execute('SELECT status FROM jobs WHERE id=?', (second['id'],)).fetchone()[0] == 'discovered'
    assert store.db.execute('SELECT state FROM applications WHERE id=?', (recorded,)).fetchone()[0] == 'unknown'
    assert (store.root / 'materials' / source['filename']).exists()


def test_unchanged_review_preserves_revision_and_drafts(store, job, package):
    source = import_material(store, b'I prefer concise letters grounded in concrete work.', 'voice.txt', 'cover_letter')
    review_material(store, source['id'], source['text'], 'style', True)
    draft = store.prepare(job, package)
    before = store.snapshot(); changes = store.db.total_changes
    assert review_material(store, source['id'], '  ' + source['text'] + '  ', 'style', True) == {'changed': False, 'drafts_removed': 0}
    assert store.snapshot() == before and store.db.total_changes == changes
    assert store.db.execute('SELECT id FROM applications WHERE id=?', (draft,)).fetchone()


def test_unapproved_excerpt_edit_does_not_discard_drafts(store, job, package):
    source = import_material(store, b'I prefer concise letters grounded in concrete work.', 'voice.txt', 'cover_letter')
    draft = store.prepare(job, package)
    result = review_material(store, source['id'], source['text'] + ' Keep a warm tone.', 'style', False)
    assert result == {'changed': True, 'drafts_removed': 0}
    assert store.db.execute('SELECT id FROM applications WHERE id=?', (draft,)).fetchone()


def test_review_failure_rolls_back_source_and_draft_invalidation(store, job, package, monkeypatch):
    source = import_material(store, b'I prefer concise letters grounded in concrete work.', 'voice.txt', 'cover_letter')
    review_material(store, source['id'], source['text'], 'style', True)
    store.prepare(job, package)
    before = store.snapshot()
    def failed(*args, **kwargs): raise OSError('Synthetic event write failure')
    monkeypatch.setattr(store, 'event', failed)
    with pytest.raises(OSError): review_material(store, source['id'], source['text'], 'style', False)
    assert store.snapshot() == before
