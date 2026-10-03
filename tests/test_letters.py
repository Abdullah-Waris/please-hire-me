from pathlib import Path
import hashlib
import pytest
from hireme.letters import generate_cover_letter,validate_generated_document,render_letter
from hireme.util import Blocked


def setup_letter(store):
    store.update_settings({'tailored_writing':True,'cover_letters':True})
    store.put_template('experience','I built Python services for operational workflows and tested them carefully.')
    class Model:
        calls=0
        def draft_answer(self,label,choices,context,maxlength):
            self.calls+=1
            return {'answer':'I enjoy building Python services for operational workflows.\n\nI test those services carefully because teams depend on them.\n\nI would like to bring that experience to this role.','sentence_ids':[choices[0]['id']]}
    return Model()


def test_cover_letter_cached_by_employer_and_sources(store,job):
    model=setup_letter(store)
    doc=generate_cover_letter(store,job,model)
    validate_generated_document(store,job,doc)
    assert generate_cover_letter(store,job,model)==doc and model.calls==1
    import fitz
    pdf=fitz.open(store.root/'documents'/doc['filename'])
    assert pdf.page_count==1
    text=pdf[0].get_text()
    assert 'Test Person' in text and 'Acme' in text and 'Sincerely,' in text
    # A deterministic fixture is rendered for human visual verification.
    pdf[0].get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save('/tmp/hireme-cover-letter.png')
    for block in pdf[0].get_text('blocks'):
        assert 40<=block[0]<block[2]<=572 and 35<=block[1]<block[3]<=757
    store.put_facts({'full_name':'Updated Person'})
    with pytest.raises(Blocked):validate_generated_document(store,job,doc)
    new=generate_cover_letter(store,job,model)
    assert new['hash']!=doc['hash']


def test_cover_letter_tampering_is_rejected(store,job):
    doc=generate_cover_letter(store,job,setup_letter(store))
    path=store.root/'documents'/doc['filename'];path.write_bytes(b'%PDF- altered')
    with pytest.raises(Blocked,match='tampered'):validate_generated_document(store,job,doc)


def test_cover_letter_needs_authorized_writing(store,job):
    with pytest.raises(Blocked,match='not_enabled'):generate_cover_letter(store,job,None)


def test_cover_letter_overflow_is_held():
    with pytest.raises(Blocked,match='too_long'):
        render_letter('Applicant','contact','Company','Role',('Long body that will not fit. '*400))


def test_cover_letter_upload_is_in_verified_package(store,job,package):
    from hireme.answers import validate_package
    doc=generate_cover_letter(store,job,setup_letter(store))
    doc['field']={'label':'Cover letter','type':'file','required':True}
    package['documents'].append(doc);package['facts_hash']=__import__('hireme.util',fromlist=['digest']).digest(store.facts())
    validate_package(store,job,package)
    other={**job,'company':'Another Employer','id':'another-job'}
    with pytest.raises(Blocked):validate_generated_document(store,other,doc)
