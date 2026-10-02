import hashlib
import pytest
from hireme.store import Store
from hireme.util import digest

@pytest.fixture
def store(tmp_path,monkeypatch):
    class OfflineProvider:
        def __init__(self,*args,**kwargs):pass
        def choose_answer(self,*args,**kwargs):return None
        def choose_sentences(self,*args,**kwargs):return []
        def match_field(self,*args,**kwargs):return {'fact_key':None,'template_id':None}
    monkeypatch.setattr('hireme.provider.ClaudeProvider',OfflineProvider)
    s=Store(tmp_path/'private')
    s.put_facts({'full_name':'Test Person','first_name':'Test','last_name':'Person','email':'test@candidate.invalid','phone':'5551234567','location':'Berkeley, CA','graduation':'2028-05','work_authorized_us':'Yes','needs_sponsorship':'No','us_person':'Yes','professional_years':'1','skills':'Python, TypeScript'})
    docs=s.root/'documents';docs.mkdir();data=b'%PDF-1.4\nsynthetic test document';h=hashlib.sha256(data).hexdigest();(docs/(h+'.pdf')).write_bytes(data)
    s.db.execute('INSERT INTO documents VALUES(?,?,?)',('resume',h,h+'.pdf'))
    s.update_settings({'onboarding_complete':True,'live_enabled':True,'browser_channel':'chromium','headless':True})
    yield s
    s.close()

@pytest.fixture
def job(store):
    url='https://jobs.lever.co/acme/req-123'
    j={'id':digest(url),'url':url,'host':'jobs.lever.co','company':'Acme','title':'Software Engineer Intern Summer 2027','location':'San Francisco, United States','description':'Build Python and TypeScript software.','source':'test'}
    store.upsert_job(j)
    return j

@pytest.fixture
def package(store,job):
    from hireme.answers import resolve
    f={'index':0,'indices':[0],'label':'Email','type':'email','required':True,'options':[],'maxlength':-1,'value':''}
    doc=dict(store.db.execute('SELECT * FROM documents').fetchone());doc['field']={'index':1,'label':'Resume','type':'file','required':True}
    return {'job_id':job['id'],'url':job['url'],'answers':[resolve(store,job['host'],f)],'documents':[doc],'facts_hash':digest(store.facts()),'steps':[{'fields':[f,doc['field']]}]}
