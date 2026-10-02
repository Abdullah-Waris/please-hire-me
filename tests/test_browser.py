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


def test_cdn_assets_hydrate_form_before_answering_and_submit(store,ats,monkeypatch):
    monkeypatch.setattr('hireme.browser.public_host',lambda host:True)
    job=local_job(store,ats)
    original=(Path(__file__).parent/'fixtures/application.html').read_text()
    script='setTimeout(()=>{document.body.innerHTML='+json.dumps(original.split('<body>')[1].split('</body>')[0].split('<script>')[0])+';document.body.removeAttribute("aria-busy");document.querySelector("form").onsubmit=async e=>{e.preventDefault();await fetch("/submit",{method:"POST",body:new FormData(e.target)});document.body.textContent="Thank you for applying. Your application has been received."};},350);'
    shell='<html><head><link rel="stylesheet" href="https://job-boards.cdn.greenhouse.io/assets/test.css"><script src="https://cdn.ashbyprd.com/frontend_non_user/test.js"></script></head><body aria-busy="true">Loading application…</body></html>'
    with Browser(store,test_url=ats[0]) as b:
        def resources(route):
            if route.request.url==ats[0]+'/application':return route.fulfill(status=200,content_type='text/html',body=shell)
            if route.request.url.endswith('test.css'):body='h1 {color:rgb(12,34,56)}';ctype='text/css'
            elif route.request.url.endswith('test.js'):body=script;ctype='text/javascript'
            else:return route.fallback()
            class Gate:
                request=route.request
                def abort(self):route.abort()
                def continue_(self):route.fulfill(status=200,content_type=ctype,body=body)
            b._route(Gate())
        b.page.route('**/*',resources)
        original_fill=b._fill
        def check_style(answer):
            assert b.page.locator('h1').evaluate('(e)=>getComputedStyle(e).color')=='rgb(12, 34, 56)'
            original_fill(answer)
        b._fill=check_style
        assert b.apply(job)=='confirmed'
    assert len(ats[1])==1
    assert not store.db.execute('SELECT 1 FROM questions WHERE resolved=0').fetchone()


def test_required_cdn_and_upload_metadata_reads_allowed_but_writes_denied(store,monkeypatch):
    monkeypatch.setattr('hireme.browser.public_host',lambda host:True)
    b=Browser(store);b.current_host='job-boards.greenhouse.io'
    class Request:
        def __init__(self,url,method='GET'):self.url=url;self.method=method;self.post_data='{}'
    class Route:
        def __init__(self,url,method='GET'):self.request=Request(url,method);self.action=None
        def abort(self):self.action='abort'
        def continue_(self):self.action='continue'
    for url in ['https://job-boards.cdn.greenhouse.io/assets/entry.css','https://cdn.ashbyprd.com/frontend_non_user/.vite/manifest.json','https://cdn.lever.co/fonts/font.woff','https://s9-recruiting.cdn.greenhouse.io/logo.png','https://boards.greenhouse.io/uncacheable_attributes/presigned_fields']:
        r=Route(url);b._route(r);assert r.action=='continue'
    for url in ['https://job-boards.cdn.greenhouse.io.attacker.invalid/entry.css','https://attacker.invalid/pixel','https://cdn.ashbyprd.com/submit']:
        r=Route(url,'POST');b._route(r);assert r.action=='abort'


def test_realistic_profile_wording_and_writing_sample_reuse_submit_without_questions(store,ats,monkeypatch):
    store.put_facts({'school':'University of California, Berkeley','degree':'B.S.','graduation':'2028-05'})
    tid=store.put_template('project','I built a Python service and measured the effect of each change.')
    class Model:
        def __init__(self,*args):pass
        def match_field(self,field,*args):return {'fact_key':None,'template_id':tid}
    monkeypatch.setattr('hireme.provider.ClaudeProvider',Model)
    job={**local_job(store,ats),'source':'gh:synthetic'}
    original=(Path(__file__).parent/'fixtures/application.html').read_text()
    additions='''<label>Which college or university do you currently attend?*<select name="school" required><option value="">Select…</option><option>Harvard University</option><option>Other</option></select></label>
    <label>Degree*<select name="degree" required><option value="">Select…</option><option>Bachelor’s degree</option></select></label>
    <label>When do you expect to graduate?*<select name="graduation" required><option value="">Select…</option><option>Spring 2028</option><option>Fall 2028</option></select></label>
    <label>How did you hear about this role?*<select name="source" required><option value="">Select…</option><option>Employee Referral</option><option>University Career Center / Job Board</option></select></label>
    <label>Please give a concrete example of a successful project<textarea name="sample" required></textarea></label>'''
    html=original.replace('</form>',additions+'</form>')
    with Browser(store,test_url=ats[0]) as b:
        def serve_form(route):
            if route.request.method=='GET':route.fulfill(status=200,content_type='text/html',body=html)
            else:route.fallback()
        b.page.route(ats[0]+'/**',serve_form)
        assert b.apply(job)=='confirmed'
    assert len(ats[1])==1
    body=ats[1][0].decode(errors='replace')
    for expected in ['Other','Bachelor’s degree','Spring 2028','University Career Center / Job Board','I built a Python service']:assert expected in body
    assert not store.db.execute('SELECT 1 FROM questions WHERE resolved=0').fetchone()


def test_upload_dom_changes_do_not_redirect_answers_to_stale_indices(store,ats):
    job=local_job(store,ats)
    html=(Path(__file__).parent/'fixtures/application.html').read_text().replace('</body>','''<script>document.querySelector('input[type=file]').addEventListener('change',()=>{
      const sentinel=document.createElement('input');sentinel.disabled=true;sentinel.value='Do not fill this';
      document.querySelector('form').prepend(sentinel);
      const hidden=document.createElement('input');hidden.required=true;hidden.value='internal-value';hidden.setAttribute('aria-hidden','true');hidden.tabIndex=-1;
      document.querySelector('form').prepend(hidden);
    });</script></body>''')
    with Browser(store,test_url=ats[0]) as b:
        def form(route):
            if route.request.method=='GET':route.fulfill(status=200,content_type='text/html',body=html)
            else:route.fallback()
        b.page.route(ats[0]+'/**',form)
        assert b.apply(job)=='confirmed'
    assert len(ats[1])==1 and b'Test Person' in ats[1][0]


def test_upload_bucket_requires_approved_file_and_response_ack(store,monkeypatch):
    monkeypatch.setattr('hireme.browser.public_host',lambda host:True)
    b=Browser(store);b.current_host='job-boards.greenhouse.io';b.upload_payloads={'approved-hash':b'%PDF-approved-content'}
    class Request:
        url='https://grnhse-prod-jben-us-west-2.s3.us-west-2.amazonaws.com/'
        method='POST'
        post_data_buffer=b'multipart-prefix%PDF-approved-contentmultipart-suffix'
    class Route:
        request=Request();action=None
        def abort(self):self.action='abort'
        def continue_(self):self.action='continue'
    r=Route();b._route(r);assert r.action=='continue'
    class Response:
        request=r.request;status=204
    b._upload_response(Response());assert 'approved-hash' in b.uploaded_files
    r.request.post_data_buffer=b'arbitrary-unapproved-file';b._route(r);assert r.action=='abort'
    r.request.url='https://attacker-bucket.s3.us-west-2.amazonaws.com/';r.request.post_data_buffer=b'%PDF-approved-content';b._route(r);assert r.action=='abort'


def test_custom_combobox_verifies_selected_option_not_empty_search_input(store,ats):
    store.put_facts({'country':'United States'})
    original=(Path(__file__).parent/'fixtures/application.html').read_text()
    html=original.replace('</form>','''<label for="country-picker">Country</label><div class="select__control">
    <span class="select__single-value">+1</span><input id="country-picker" role="combobox">
    <input type="hidden" name="country" value="Canada +1"></div>
    <div id="menu" role="listbox" hidden><div role="option" aria-selected="false">United States +1</div><div role="option" aria-selected="true">Canada +1</div></div></form>''').replace('</body>','''<script>
    const picker=document.querySelector('#country-picker'),menu=document.querySelector('#menu');
    picker.onclick=()=>{menu.hidden=false};picker.onkeydown=e=>{if(e.key==='Escape')menu.hidden=true};
    menu.querySelectorAll('[role=option]').forEach(option=>option.onclick=()=>{
      menu.querySelectorAll('[role=option]').forEach(x=>x.setAttribute('aria-selected',x===option?'true':'false'));
      document.querySelector('[name=country]').value=option.textContent;picker.value='';menu.hidden=true;
    });</script></body>''')
    with Browser(store,test_url=ats[0]) as b:
        def form(route):
            if route.request.method=='GET':route.fulfill(status=200,content_type='text/html',body=html)
            else:route.fallback()
        b.page.route(ats[0]+'/**',form)
        assert b.apply(local_job(store,ats))=='confirmed'
    assert b'United States +1' in ats[1][0]


def test_acknowledged_upload_can_remove_original_file_input(store,ats):
    job=local_job(store,ats)
    html=(Path(__file__).parent/'fixtures/application.html').read_text().replace('</body>','''<script>
    document.querySelector('input[type=file]').addEventListener('change',e=>{
      const name=e.target.files[0].name;const label=document.createElement('span');label.textContent=name;
      e.target.replaceWith(label);
    });</script></body>''')
    with Browser(store,test_url=ats[0]) as b:
        def form(route):
            if route.request.method=='GET':route.fulfill(status=200,content_type='text/html',body=html)
            else:route.fallback()
        b.page.route(ats[0]+'/**',form)
        original=b._verify
        def ack(answers,documents,fields):
            # Equivalent to the independently tested successful upload response callback.
            b.uploaded_files.update(d['hash'] for d in documents)
            return original(answers,documents,fields)
        b._verify=ack
        assert b.apply(job)=='confirmed'
    assert len(ats[1])==1


def test_phone_country_flag_verification_ignores_other_dropdown_options(store,ats):
    store.put_facts({'country':'United States'})
    original=(Path(__file__).parent/'fixtures/application.html').read_text()
    html=original.replace('</form>','''<label for="country-picker">Country</label><div class="select__control">
    <span class="select__single-value"><i class="iti__flag iti__ca"></i>+1</span>
    <input id="country-picker" role="combobox" aria-controls="country-menu"><input type="hidden" name="country" value="Canada +1"></div>
    <div id="country-menu" role="listbox" hidden><div role="option"><i class="iti__flag iti__us"></i>United States +1</div><div role="option"><i class="iti__flag iti__ca"></i>Canada +1</div></div>
    <div role="option" hidden><i class="iti__flag iti__us"></i>United States+1</div></form>''').replace('</body>','''<script>
    const picker=document.querySelector('#country-picker'),menu=document.querySelector('#country-menu');
    picker.onclick=()=>{menu.hidden=false};picker.onkeydown=e=>{if(e.key==='Escape')menu.hidden=true};
    menu.querySelectorAll('[role=option]').forEach(option=>option.onclick=()=>{
      const code=option.querySelector('i').className;document.querySelector('.select__single-value i').className=code;
      document.querySelector('[name=country]').value=option.textContent;picker.value='';menu.hidden=true;
    });</script></body>''')
    with Browser(store,test_url=ats[0]) as b:
        def form(route):
            if route.request.method=='GET':route.fulfill(status=200,content_type='text/html',body=html)
            else:route.fallback()
        b.page.route(ats[0]+'/**',form)
        assert b.apply(local_job(store,ats))=='confirmed'
    assert b'United States +1' in ats[1][0]


def test_header_apply_button_does_not_compete_with_form_submit(store,ats):
    job=local_job(store,ats)
    html=(Path(__file__).parent/'fixtures/application.html').read_text().replace('<body>','<body><button type="button">Apply</button>')
    with Browser(store,test_url=ats[0]) as b:
        def form(route):
            if route.request.method=='GET':route.fulfill(status=200,content_type='text/html',body=html)
            else:route.fallback()
        b.page.route(ats[0]+'/**',form)
        assert b.apply(job)=='confirmed'
    assert len(ats[1])==1
