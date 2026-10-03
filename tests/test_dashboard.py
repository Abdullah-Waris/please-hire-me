import json
import multiprocessing
import socket
import time
import urllib.error
import urllib.request
from hireme.server import serve
from pathlib import Path


def launch(root,repo,port):serve(Path(root),Path(repo),port,token="fixture-capability")


def test_dashboard_capability_csrf_host_and_xss(tmp_path):
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    process=multiprocessing.Process(target=launch,args=(str(tmp_path/'private'),str(Path(__file__).parent.parent),port))
    process.start()
    base=f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(base) as r:
                    assert "frame-ancestors 'none'" in r.headers['Content-Security-Policy'];assert r.headers['Referrer-Policy']=='no-referrer'
                    html=r.read().decode();assert 'application desk' in html.lower()
                break
            except OSError:time.sleep(.1)
        for headers in ({},{'Host':'attacker.invalid'},{'X-Hireme-Token':'wrong','Origin':'https://attacker.invalid'}):
            try:urllib.request.urlopen(urllib.request.Request(base+'/api/state',headers=headers));assert False
            except urllib.error.HTTPError as e:assert e.code==403
        req=urllib.request.Request(base+'/api/facts',data=json.dumps({'facts':{'full_name':'Synthetic <img onerror=alert(1)>'}}).encode(),headers={'X-Hireme-Token':'fixture-capability','Content-Type':'application/json','Origin':base})
        with urllib.request.urlopen(req) as r:assert r.status==200
        req=urllib.request.Request(base+'/api/state',headers={'X-Hireme-Token':'fixture-capability'})
        with urllib.request.urlopen(req) as r:assert json.loads(r.read())['facts']['full_name']['confirmed']==1
        req=urllib.request.Request(base+'/api/pause',data=b'{}',headers={'X-Hireme-Token':'fixture-capability','Content-Type':'application/json','Origin':base})
        with urllib.request.urlopen(req) as r:assert json.loads(r.read())['paused'] is True
        from hireme.store import Store
        control=Store(tmp_path/'private')
        assert not control.settings()['live_enabled'] and control.control_generation()==1
        control.close()
        js=Path('hireme/static/app.js').read_text()
        assert '.innerHTML' not in js and 'textContent' in js
    finally:
        process.terminate();process.join(5)


def test_transcript_upload_replace_invalid_and_responsive_ui(tmp_path):
    from pypdf import PdfWriter
    from playwright.sync_api import sync_playwright, expect
    from hireme.store import Store
    root=tmp_path/'private'
    store=Store(root)
    store.db.execute('INSERT INTO documents VALUES(?,?,?)',('resume','original','original.pdf'))
    store.close()
    transcript=tmp_path/'transcript.pdf'
    writer=PdfWriter();writer.add_blank_page(width=612,height=792)
    with transcript.open('wb') as f:writer.write(f)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    process=multiprocessing.Process(target=launch,args=(str(root),str(Path(__file__).parent.parent),port));process.start()
    base=f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try:urllib.request.urlopen(base).close();break
            except OSError:time.sleep(.1)
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/#token=fixture-capability')
            page.locator('[data-view="profile"]').click()
            expect(page.locator('#transcript-state')).to_contain_text('No transcript imported')
            page.locator('#transcript-upload').set_input_files(str(transcript))
            expect(page.locator('#transcript-state')).to_contain_text('Transcript imported')
            store=Store(root);original=store.db.execute("SELECT hash FROM documents WHERE kind='transcript'").fetchone()[0]
            assert store.db.execute("SELECT hash FROM documents WHERE kind='resume'").fetchone()[0]=='original'
            assert (root/'documents'/(original+'.pdf')).read_bytes()==transcript.read_bytes()
            assert not store.facts()
            page.locator('#transcript-upload').set_input_files({'name':'invalid.pdf','mimeType':'application/pdf','buffer':b'not a PDF'})
            expect(page.locator('#notice')).to_contain_text('Not a PDF')
            assert store.db.execute("SELECT hash FROM documents WHERE kind='transcript'").fetchone()[0]==original
            writer.add_blank_page(width=612,height=792)
            with transcript.open('wb') as f:writer.write(f)
            page.locator('#transcript-upload').set_input_files(str(transcript))
            expect(page.locator('#notice')).to_contain_text('Transcript saved')
            updated=store.db.execute("SELECT hash FROM documents WHERE kind='transcript'").fetchone()[0]
            assert updated!=original
            for width,height,name in [(1440,1000,'desktop'),(390,844,'mobile')]:
                page.set_viewport_size({'width':width,'height':height})
                page.locator('#transcript-state').scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                captures=Path('tmp/ui');captures.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(captures/('transcript-'+name+'.png')))
            assert not errors
            store.close();browser.close()
    finally:process.terminate();process.join(5)


def launch_setup(root,repo,port,queue):
    from hireme import scheduler,worker,setup_status
    setup_status.readiness=lambda store,verify=False: {'supported_platform':True,'browser_ready':True,'provider':{'ready':True}}
    scheduler.install=lambda store,repo:'fixture scheduler'
    worker.cycle=lambda store,repo:queue.put('first cycle started')
    serve(Path(root),Path(repo),port,token='fixture-capability')


def test_complete_setup_installs_schedule_and_starts_first_cycle(store):
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    queue=multiprocessing.Queue()
    process=multiprocessing.Process(target=launch_setup,args=(str(store.root),str(Path(__file__).parent.parent),port,queue));process.start()
    base=f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try:urllib.request.urlopen(base).close();break
            except OSError:time.sleep(.1)
        req=urllib.request.Request(base+'/api/complete-setup',data=b'{"start":true}',headers={'X-Hireme-Token':'fixture-capability','Content-Type':'application/json','Origin':base})
        with urllib.request.urlopen(req) as response:
            assert 'First cycle started' in json.loads(response.read())['message']
        assert queue.get(timeout=5)=='first cycle started'
        assert store.settings()['live_enabled']
    finally:process.terminate();process.join(5);queue.close()


def test_material_upload_review_and_context_preferences(tmp_path):
    from playwright.sync_api import sync_playwright,expect
    from hireme.store import Store
    root=tmp_path/'private'
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    process=multiprocessing.Process(target=launch,args=(str(root),str(Path(__file__).parent.parent),port));process.start()
    base=f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try:urllib.request.urlopen(base).close();break
            except OSError:time.sleep(.1)
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':1280,'height':900});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base+'/#token=fixture-capability')
            page.locator('[data-view="materials"]').click()
            page.locator('#material-upload-form input[type=file]').set_input_files({'name':'research-notes.txt','mimeType':'text/plain','buffer':b'I built Python services for an operational workflow and tested their behavior.'})
            page.locator('#material-upload-form button').click()
            expect(page.locator('#material-list')).to_contain_text('Needs review')
            form=page.locator('.material-review')
            form.locator('select').select_option('personal');form.locator('input[type=checkbox]').check();form.locator('button').click()
            expect(page.locator('#material-list')).to_contain_text('Approved')
            store=Store(root)
            assert store.db.execute('SELECT confirmed,role FROM materials').fetchone()[0]==1
            assert len(store.templates())==1 and not store.facts()
            store.close()
            page.screenshot(path='/tmp/hireme-materials-desktop.png',full_page=True)
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path='/tmp/hireme-materials-mobile.png',full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            page.locator('[data-view="settings"]').click()
            page.locator('[name=tailored_writing]').check();page.locator('[name=contextual_preferences]').check()
            page.locator('#settings-form button[type=submit]').click()
            expect(page.locator('#notice')).to_contain_text('Search preferences saved')
            store=Store(root);assert store.settings()['tailored_writing'] and store.settings()['contextual_preferences'];store.close()
            assert not errors
            browser.close()
    finally:
        process.terminate();process.join(5)


def launch_wizard(root,repo,port):
    import hireme.setup_status
    def readiness(store,verify=False):
        return {'platform':'linux','architecture':'aarch64','python':'3.11','browser_ready':True,'provider':{'ready':True,'message':'Fixture login verified.'},'missing':store.missing_setup(),'deployment':store.settings()['deployment'],'supported_platform':True}
    hireme.setup_status.readiness=readiness
    serve(Path(root),Path(repo),port,token='fixture-capability')


def test_fresh_user_guided_setup_saves_paused_and_provider_key_private(tmp_path):
    from reportlab.pdfgen import canvas
    from playwright.sync_api import sync_playwright,expect
    from hireme.store import Store
    resume=tmp_path/'resume.pdf';c=canvas.Canvas(str(resume));c.drawString(72,740,'Example Candidate');c.drawString(72,720,'candidate@synthetic.invalid');c.save()
    root=tmp_path/'fresh';sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    process=multiprocessing.Process(target=launch_wizard,args=(str(root),str(Path.cwd()),port));process.start();base=f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try:urllib.request.urlopen(base).close();break
            except OSError:time.sleep(.1)
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':1280,'height':900});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)));page.goto(base+'/#token=fixture-capability')
            expect(page.locator('#heading')).to_have_text('Make it yours')
            page.screenshot(path='/tmp/hireme-setup-desktop.png',full_page=True)
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path='/tmp/hireme-setup-mobile.png',full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.locator('#begin-setup').click();page.locator('#setup-next').click()
            expect(page.locator('#notice')).to_contain_text('Import a resume')
            page.locator('#resume-upload').set_input_files(str(resume));expect(page.locator('#resume-state')).to_contain_text('Resume imported')
            page.locator('#setup-next').click();expect(page.locator('#guided-label')).to_contain_text('Step 2')
            values={'full_name':'Example Candidate','first_name':'Example','last_name':'Candidate','email':'candidate@synthetic.invalid','phone':'5551234567','location':'Berkeley, CA','graduation':'2028-05','work_authorized_us':'Yes','needs_sponsorship':'No','us_person':'Yes','professional_years':'0','skills':'Python'}
            for key,value in values.items():page.locator('#facts-form [name="'+key+'"]').fill(value)
            page.locator('#confirm-facts').check();page.locator('#facts-form button').click();expect(page.locator('#notice')).to_contain_text('Confirmed facts saved')
            page.locator('#setup-next').click();expect(page.locator('#guided-label')).to_contain_text('Step 3')
            page.locator('#context-form textarea').fill('I built a Python tool that helps students organize their coursework.')
            page.locator('#context-form input[type=checkbox]').check();page.locator('#context-form button').click();expect(page.locator('#notice')).to_contain_text('Approved context saved')
            page.locator('#setup-next').click();page.locator('#setup-next').click();expect(page.locator('#guided-label')).to_contain_text('Step 5')
            page.locator('#settings-form [name=seniority]').fill('internship');page.locator('#settings-form [name=max_attempts_per_cycle]').fill('2');page.locator('#settings-form button').click();expect(page.locator('#notice')).to_contain_text('Search preferences saved')
            page.locator('#setup-next').click();page.locator('#setup-next').click();expect(page.locator('#guided-label')).to_contain_text('Step 7')
            page.locator('#provider-form [name=provider]').select_option('openai-api');page.locator('#provider-form [name=provider_model]').fill('fixture-model');page.locator('#provider-form [name=key]').fill('synthetic-private-provider-key');page.locator('#provider-form button').click();expect(page.locator('#notice')).to_contain_text('Connection saved')
            assert page.locator('#provider-form [name=key]').input_value()==''
            page.locator('#finish-paused').click();expect(page.locator('#notice')).to_contain_text('Applications remain paused')
            ledger=Store(root)
            assert ledger.settings()['onboarding_complete'] and not ledger.settings()['live_enabled']
            assert ledger.settings()['seniority']==['internship']
            assert ledger.settings()['max_attempts_per_cycle']==2 and ledger.settings()['provider']=='openai-api'
            assert 'synthetic-private-provider-key' not in json.dumps(ledger.snapshot())
            assert ledger.db.execute('SELECT count(*) FROM materials WHERE confirmed=1').fetchone()[0]==1
            ledger.close();assert not errors;browser.close()
    finally:process.terminate();process.join(5)
