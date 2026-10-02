import json
import pytest
from hireme.answers import resolve,validate_package
from hireme.util import Blocked


def field(label,kind='text',options=None):
    return {'label':label,'type':kind,'required':True,'options':options or [],'maxlength':-1}


def test_profile_question_variations_and_presentation_options(store,job):
    store.put_facts({'school':'University of California, Berkeley','degree':'B.S.','onsite':'Yes','country':'United States'})
    assert resolve(store,job['host'],field('Which college or university do you currently attend?*'))['value']=='University of California, Berkeley'
    assert resolve(store,job['host'],field('Degree*','select',["Bachelor’s degree","Master’s degree"]))['value']=='Bachelor’s degree'
    assert resolve(store,job['host'],field('Will you now or in the future require sponsorship for employment visa status (e.g., H-1B status)?*','select',['Yes','No']))['value']=='No'
    assert resolve(store,job['host'],field('Are you open to working in-person in one of our offices 25% of the time?*','select',['Yes','No']))['value']=='Yes'
    with pytest.raises(Blocked):resolve(store,job['host'],field('What is your highest level of education?*'))


def test_semantic_fact_selection_is_cached_revision_checked_and_clears_queue(store,job,package):
    class Model:
        calls=0
        def match_field(self,*args):self.calls+=1;return {'fact_key':'school','template_id':None}
    store.put_facts({'school':'Confirmed University'})
    host=job['host'];f=field('Where are you studying right now?')
    q=store.ask(job['id'],host,f['label'],[]);model=Model()
    a=resolve(store,host,f,model)
    assert a['value']=='Confirmed University' and model.calls==1
    assert store.db.execute('SELECT resolved FROM questions WHERE id=?',(q,)).fetchone()[0]==1
    assert resolve(store,host,f)==a
    package['answers']=[a];package['steps']=[];package['facts_hash']=__import__('hireme.util',fromlist=['digest']).digest(store.facts())
    validate_package(store,job,package)
    store.put_facts({'school':'Another Confirmed University'})
    with pytest.raises(Blocked):validate_package(store,job,package)


def test_model_cannot_invent_fact_or_confuse_current_and_completed_degree(store,job):
    class Model:
        def match_field(self,*args):return {'fact_key':'made_up_fact','template_id':None}
    with pytest.raises(Blocked):resolve(store,job['host'],field('Unknown factual question'),Model())
    store.put_facts({'degree':'B.S.'})
    class WrongDegree:
        def match_field(self,*args):return {'fact_key':'degree','template_id':None}
    with pytest.raises(Blocked):resolve(store,job['host'],field('What is the highest education you have completed?'),WrongDegree())


def test_writing_uses_approved_sentences_omits_other_employer_and_is_immutable(store,job,package):
    tid=store.put_template('motivation','Hadrian feels close to my manufacturing work. I built Python services around production workflows. Hadrian is interesting for the same reason.')
    class Model:
        def choose_answer(self,*args):return None
        def match_field(self,*args):return {'fact_key':None,'template_id':None}
        def choose_sentences(self,label,choices,*args):
            assert not any('Hadrian' in c['text'] for c in choices)
            return [c['id'] for c in choices]
    # A second sample forces semantic selection instead of unconditional single-template reuse.
    store.put_template('motivation','Seldon especially caught my attention. I tested models against recorded research traces.')
    f=field('Why are you interested in joining Acme?','textarea')
    a=resolve(store,job['host'],f,Model(),context=job)
    assert a['value']=='I built Python services around production workflows. I tested models against recorded research traces.'
    assert resolve(store,job['host'],f)==a
    package['answers']=[a];package['steps']=[]
    validate_package(store,job,package)
    a['value']+=' I served a million users.'
    with pytest.raises(Blocked):validate_package(store,job,package)


def test_untrusted_work_samples_and_options_still_block(store,job):
    class Model:
        def match_field(self,*args):raise AssertionError('Must not call Claude for forbidden work')
    with pytest.raises(Blocked,match='human_work_sample'):resolve(store,job['host'],field('Solve this coding challenge'),Model())
    with pytest.raises(Blocked,match='option_mismatch'):resolve(store,job['host'],field('Will you require sponsorship?','select',['Yes','Unknown']))


def test_graduation_season_school_alias_and_discovery_source(store,job):
    store.put_facts({'school':'University California Berkeley','graduation':'2028-05'})
    assert resolve(store,job['host'],field('Which university do you currently attend?','select',['UC Berkeley','Other']))['value']=='UC Berkeley'
    class Model:
        def match_field(self,*args):return {'fact_key':'graduation','template_id':None}
    assert resolve(store,job['host'],field('When do you expect to graduate?','select',['Fall 2027','Spring 2028']),Model())['value']=='Spring 2028'
    source={**job,'source':'gh:acme'}
    answer=resolve(store,job['host'],field('How did you hear about this role?','select',['LinkedIn','University Career Center / Job Board','Other']),context=source)
    assert answer['value']=='Other' and answer['provenance']['job_source']=='gh:acme'


def test_single_company_specific_sample_is_adapted_not_copied(store,job):
    store.put_template('motivation','Hadrian feels close to my work. I built manufacturing software using Python.')
    class Model:
        def choose_sentences(self,label,choices,*args):return [c['id'] for c in choices]
    a=resolve(store,job['host'],field('Why do you want this role?','textarea'),Model(),context=job)
    assert a['value']=='I built manufacturing software using Python.'


def test_closed_school_and_composite_job_board_option_use_known_sources(store,job):
    store.put_facts({'school':'University of California, Berkeley'})
    a=resolve(store,job['host'],field('Which college or university do you currently attend?','select',['Harvard University','Other']))
    assert a['value']=='Other' and a['provenance']['fact_key']=='school'
    a=resolve(store,job['host'],field('How did you hear about this role?','select',['Employee Referral','University Career Center / Job Board']),context={**job,'source':'gh:acme'})
    assert a['value']=='University Career Center / Job Board'
    with pytest.raises(Blocked):resolve(store,job['host'],field('How did you hear about this role?','select',['Employee Referral','LinkedIn']),context={**job,'source':'gh:acme'})


def test_scoped_history_and_summer_preferences_not_offered_as_universal_facts(store,job):
    store.put_facts({'worked_outside_resume':'No','contacts_outside_resume':'No','summer_2027_relocate':'Yes'})
    store.update_settings({'prior_employers':['Acme']})
    class Model:
        def match_field(self,f,facts,*args):
            assert 'worked_outside_resume' not in facts and 'contacts_outside_resume' not in facts
            assert 'summer_2027_relocate' not in facts
            return {'fact_key':None,'template_id':None}
    with pytest.raises(Blocked):resolve(store,job['host']+'|acme',field('Have you ever been employed by this company?'),Model(),context={**job,'title':'Software Engineer Fall 2027'})


def test_prior_internship_uses_hashed_resume_evidence_and_rejects_future_only(store,tmp_path,job):
    from pypdf import PdfWriter
    from pypdf.generic import NameObject,DictionaryObject,DecodedStreamObject
    import hashlib
    def resume(year):
        writer=PdfWriter();page=writer.add_blank_page(width=612,height=792)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(f'BT /F1 12 Tf 50 700 Td (EXPERIENCE) Tj 0 -14 Td (Acme - 01/{year} - 03/{year}) Tj 0 -14 Td (AI Engineer Intern) Tj ET'.encode())
        page[NameObject('/Contents')]=writer._add_object(stream)
        path=tmp_path/f'resume-{year}.pdf'
        with path.open('wb') as f:writer.write(f)
        data=path.read_bytes();h=hashlib.sha256(data).hexdigest();(store.root/'documents'/(h+'.pdf')).write_bytes(data)
        store.db.execute("UPDATE documents SET hash=?,filename=? WHERE kind='resume'",(h,h+'.pdf'))
        return h
    h=resume('2020');f=field('Do you have prior internship or co-op experience?','select',['Yes','No'])
    a=resolve(store,job['host'],f)
    assert a['value']=='Yes' and a['provenance']['resume_hash']==h and a['provenance']['resume_quote']=='AI Engineer Intern'
    resume('2099')
    with pytest.raises(Blocked):resolve(store,job['host'],f)


def test_semantic_model_cannot_turn_unrelated_boolean_into_new_claim(store,job):
    class Model:
        def match_field(self,*args):return {'fact_key':'needs_sponsorship','template_id':None}
    with pytest.raises(Blocked):resolve(store,job['host'],field('Have you published five research papers?','select',['Yes','No']),Model())


def test_long_writing_sample_is_assembled_within_question_sentence_limit(store,job,package):
    store.put_template('project','I built a Python service. I added tracing. I measured latency. I improved retries. I documented the rollout.')
    class Model:
        def choose_sentences(self,label,choices,*args):return [c['id'] for c in choices[:3]]
    f=field('Describe a project you built in 3-4 sentences.','textarea')
    a=resolve(store,job['host'],f,Model(),context=job)
    assert a['value']=='I built a Python service. I added tracing. I measured latency.'
    assert len(a['provenance']['sample_parts'])==3
    package['answers']=[a];package['steps']=[]
    validate_package(store,job,package)


def test_sample_selection_cannot_exceed_word_limit(store,job):
    store.put_template('project','I built a Python service and measured every deployment carefully.')
    class Model:
        def choose_sentences(self,label,choices,*args):return [c['id'] for c in choices]
    with pytest.raises(Blocked,match='answer_too_long'):resolve(store,job['host'],field('Describe a project you built; maximum 5 words.','textarea'),Model(),context=job)


def test_numbered_examples_inherit_shared_sentence_limit(store,job,package):
    tid=store.put_template('project','I built a service. I added tracing. I measured latency. I improved retries. I documented the rollout.')
    instruction=field('Each bullet should be concise, no longer than 3-4 sentences each. First example:','textarea')
    instruction['required']=False
    class Model:
        def match_field(self,*args):return {'fact_key':None,'template_id':tid}
        def choose_sentences(self,label,choices,context,*args):
            assert context['max_sentences']==4
            return [c['id'] for c in choices[:3]]
    f=field('Second example:','textarea')
    a=resolve(store,job['host'],f,Model(),context={**job,'form_questions':[instruction['label'],f['label']]})
    assert len(a['provenance']['sample_parts'])==3
    package['answers']=[a];package['steps']=[{'fields':[instruction,f]}]
    validate_package(store,job,package)


def test_cached_writing_is_reassembled_for_a_shorter_field(store,job):
    store.put_template('project','I built a service. I added tracing. I measured latency. I improved retries. I documented the rollout.')
    class Model:
        def choose_sentences(self,label,choices,context,maxlength):return [c['id'] for c in choices[:1 if maxlength<30 else 3]]
    f=field('Describe a project you built','textarea');f['maxlength']=70
    first=resolve(store,job['host'],f,Model(),context=job)
    f['maxlength']=27
    shorter=resolve(store,job['host'],f,Model(),context=job)
    assert len(shorter['value'])<len(first['value']) and shorter['value']=='I built a service.'
    assert resolve(store,job['host'],f,context=job)==shorter
