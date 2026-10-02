import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import pytest
from hireme.browser import Browser
from hireme.util import Blocked,digest

@pytest.fixture
def ats():
    records=[];html=(Path(__file__).parent/'fixtures/application.html').read_bytes()
    class H(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(html)
        def do_POST(self):
            records.append(self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(200);self.end_headers();self.wfile.write(b'OK')
    server=ThreadingHTTPServer(('127.0.0.1',0),H)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    yield 'http://127.0.0.1:'+str(server.server_address[1]),records
    server.shutdown();server.server_close()


def local_job(store,ats):
    url=ats[0]+'/application';j={'id':digest(url),'url':url,'host':'127.0.0.1','company':'Synthetic ATS','title':'Software Engineer Intern Summer 2027','location':'San Francisco, United States','description':'Build Python and TypeScript software','source':'fixture'}
    store.upsert_job(j);return j


def test_local_exact_answers_upload_confirm_and_no_retry(store,ats):
    job=local_job(store,ats)
    with Browser(store,test_url=ats[0]) as b:
        assert b.apply(job)=='confirmed'
        with pytest.raises(Blocked):b.apply(job)
    assert len(ats[1])==1
    body=ats[1][0].decode(errors='replace');assert 'Test Person' in body and 'test@candidate.invalid' in body and 'No' in body
    app=store.db.execute('SELECT * FROM applications').fetchone()
    assert app['state']=='confirmed'
    assert len(json.loads(app['package'])['answers'])==3
    assert (store.root/'screenshots'/app['screenshot']).is_file()


def test_prepare_only_never_submits(store,ats):
    with Browser(store,test_url=ats[0]) as b:assert b.apply(local_job(store,ats),live=False)=='prepared'
    assert not ats[1]


def test_unknown_field_blocks_before_click(store,ats):
    job=local_job(store,ats)
    with Browser(store,test_url=ats[0]) as b:
        original=b._snapshot
        def injected():
            fields=original();fields.append({'index':99,'indices':[99],'label':'Invent a SAT score','type':'text','required':True,'options':[],'maxlength':-1,'value':''});return fields
        b._snapshot=injected
        with pytest.raises(Blocked,match='SAT'):b.apply(job)
    assert not ats[1]
    assert store.db.execute('SELECT count(*) FROM questions').fetchone()[0]==1


def test_route_denies_private_or_unapproved_write(store,monkeypatch):
    monkeypatch.setattr('hireme.browser.public_host',lambda h:h!='127.0.0.1')
    b=Browser(store);b.current_host='jobs.lever.co'
    class Request:
        def __init__(self,url,method='GET',post_data=None):self.url=url;self.method=method;self.post_data=post_data
    class Route:
        def __init__(self,request):self.request=request;self.action=None
        def abort(self):self.action='abort'
        def continue_(self):self.action='continue'
    for url,method in [('https://127.0.0.1/secret','GET'),('https://attacker.invalid/pixel?personal=data','GET'),('https://jobs.lever.co/acme/submit','POST')]:
        r=Route(Request(url,method));b._route(r);assert r.action=='abort'
    b.attempted=True
    r=Route(Request('https://jobs.lever.co/acme/submit','POST'));b._route(r);assert r.action=='continue'


def test_login_captcha_and_personal_tab_isolation(store,ats):
    job=local_job(store,ats)
    with Browser(store,test_url=ats[0]) as b:
        b.page.goto(ats[0])
        b.page.set_content('<label>Password<input type=password></label>')
        with pytest.raises(Blocked,match='account'):b._guard(job)
        b.page.set_content('<iframe src="https://captcha.invalid/bframe"></iframe>')
        with pytest.raises(Blocked,match='captcha'):b._guard(job)
        # Only a private persistent context is opened; no CDP attachment to everyday Chrome.
        assert len(b.context.pages)==1
    assert not ats[1]


def test_required_transcript_blocks_until_imported_then_attaches(store,ats,tmp_path):
    import hashlib
    from pypdf import PdfWriter
    from hireme.onboarding import import_resume
    job=local_job(store,ats)
    html=(Path(__file__).parent/'fixtures/application.html').read_text().replace('</form>','<label>Transcript<input type="file" name="transcript" required></label></form>')
    def serve_form(route):
        if route.request.method=='GET':route.fulfill(status=200,content_type='text/html',body=html)
        else:route.fallback()
    with Browser(store,test_url=ats[0]) as b:
        b.page.route(ats[0]+'/**',serve_form)
        with pytest.raises(Blocked,match='Transcript'):b.apply(job)
    assert not ats[1]
    transcript=tmp_path/'transcript.pdf';writer=PdfWriter();writer.add_blank_page(width=612,height=792)
    with transcript.open('wb') as f:writer.write(f)
    imported=import_resume(store,transcript,'transcript')
    with Browser(store,test_url=ats[0]) as b:
        b.page.route(ats[0]+'/**',serve_form)
        assert b.apply(job)=='confirmed'
    assert len(ats[1])==1
    package=json.loads(store.db.execute('SELECT package FROM applications').fetchone()[0])
    doc=next(d for d in package['documents'] if d['kind']=='transcript')
    assert doc['hash']==imported['hash']==hashlib.sha256(transcript.read_bytes()).hexdigest()
