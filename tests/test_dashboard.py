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
            page.locator('[data-view="settings"]').click()
            expect(page.locator('[name="employer_accounts"]')).not_to_be_checked()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.locator('[name="employer_accounts"]').check()
            captures=tmp_path/'ui';captures.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(captures/'employer-preferences-mobile.png'))
            page.get_by_role('button',name='Save preferences',exact=True).click()
            expect(page.locator('#notice')).to_contain_text('Search preferences saved')
            assert store.settings()['employer_accounts'] is True
            from hireme.accounts import AccountVault
            store.put_facts({'email':'test@candidate.invalid'})
            vault=AccountVault(store)
            vault.credentials('https://careers.example.com','Synthetic employer',create=True)
            key=vault.begin_creation('https://careers.example.com','Synthetic employer')
            vault.finish_creation(key,confirmed=False)
            page.reload()
            page.locator('[data-view="questions"]').click()
            evidence=page.get_by_label('Account confirmation evidence for Synthetic employer')
            expect(evidence).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            evidence.scroll_into_view_if_needed()
            page.screenshot(path=str(captures/'employer-account-mobile.png'))
            evidence.fill('Verified account exists and sign-in succeeded in dedicated browser')
            page.get_by_role('button',name='Confirm verified account',exact=True).click()
            expect(page.locator('#notice')).to_contain_text('Account confirmed')
            assert store.db.execute('SELECT state FROM employer_accounts WHERE id=?',(key,)).fetchone()[0]=='confirmed'
            page.locator('[data-view="profile"]').click()
            for width,height,name in [(1440,1000,'desktop'),(390,844,'mobile')]:
                page.set_viewport_size({'width':width,'height':height})
                page.locator('#transcript-state').scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                captures=tmp_path/'ui';captures.mkdir(parents=True,exist_ok=True)
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


def test_workspace_real_counts_search_sort_and_mobile_navigation(store, tmp_path):
    """Exercise the redesigned ledger against persisted synthetic application states."""
    from playwright.sync_api import sync_playwright, expect
    from hireme.discovery import posting
    from hireme.util import now

    jobs = []
    for index, (company, location, status, score) in enumerate([
        ('Cedar Labs', 'New York', 'confirmed', 91),
        ('Atlas Research', 'Remote (US)', 'blocked', 82),
        ('Meridian', 'Seattle', 'discovered', 75),
    ]):
        job = posting(f'https://jobs.lever.co/workspace/req-{index}', company,
                      'Software Engineer Intern', location, 'fixture')
        store.upsert_job(job)
        store.db.execute('UPDATE jobs SET status=?,score=? WHERE id=?', (status, score, job['id']))
        jobs.append(job)
    stamp = now()
    store.db.execute('''INSERT INTO applications
        (id,job_id,company_key,state,package,hash,created,updated,attempted)
        VALUES(?,?,?,?,?,?,?,?,?)''',
        ('fixture-submission', jobs[0]['id'], 'cedar labs', 'confirmed',
         '{"answers":[]}', 'fixture', stamp, stamp, stamp))
    # A blocked job with a question should count once in the attention queue.
    store.db.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,0)',
                     ('fixture-question', jobs[1]['id'], jobs[1]['host'],
                      'Which work location do you prefer?', '["Remote", "New York"]', 'unknown_fact'))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port))
    process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability')
            expect(page.locator('#metric-submitted')).to_have_text('1')
            expect(page.locator('#metric-attention')).to_have_text('1')
            expect(page.locator('#metric-opportunities')).to_have_text('3')
            expect(page.locator('#jobs tbody tr')).to_have_count(3)
            page.locator('#job-sort').select_option('company')
            expect(page.locator('#jobs tbody tr').first).to_contain_text('Atlas Research')
            page.locator('#job-sort').select_option('fit')
            expect(page.locator('#jobs tbody tr').first).to_contain_text('Cedar Labs')
            captures = tmp_path / 'workspace'; captures.mkdir()
            page.screenshot(path=str(captures / 'overview-desktop.png'), full_page=True)
            page.locator('#job-search').fill('remote')
            expect(page.locator('#jobs tbody tr')).to_have_count(1)
            expect(page.locator('#jobs')).to_contain_text('Atlas Research')
            page.locator('#status-filter').select_option('confirmed')
            expect(page.locator('#jobs')).to_contain_text('No matching opportunities')
            page.locator('#job-search').fill('')
            expect(page.locator('#jobs tbody tr')).to_have_count(1)
            page.locator('#status-filter').select_option('all')
            page.locator('#add-posting').click()
            expect(page.locator('#job-form [name=company]')).to_be_focused()
            page.locator('#job-form [name=company]').fill('Synthetic <img onerror=alert(1)>')
            page.locator('#job-form [name=title]').fill('Research Engineering Intern')
            page.locator('#job-form [name=url]').fill('https://jobs.lever.co/workspace/req-added')
            page.locator('#job-form [name=location]').fill('Remote (US)')
            page.locator('#job-form button').click()
            expect(page.locator('#metric-opportunities')).to_have_text('4')
            expect(page.locator('#jobs')).to_contain_text('Synthetic <img onerror=alert(1)>')
            assert page.locator('#jobs img').count() == 0
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path=str(captures / 'overview-mobile.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#review-queue').click()
            expect(page.locator('#heading')).to_have_text('A few things need you')
            expect(page.locator('#question-list')).to_contain_text('Which work location')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('[data-view=settings]').click()
            expect(page.get_by_role('group', name='Your pace')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(captures / 'preferences-mobile.png'), full_page=True)
            assert not errors
            browser.close()
    finally:
        process.terminate(); process.join(5)


def launch_demo(root, repo, port):
    from hireme.demo import seed
    from hireme.store import Store
    store = Store(Path(root)); seed(store); store.close()
    serve(Path(root), Path(repo), port, token='fixture-capability', demo=True)


def test_demo_is_read_only_and_export_requires_auth(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    root = tmp_path / 'sample'
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch_demo, args=(str(root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        try: urllib.request.urlopen(base + '/api/export.csv'); assert False
        except urllib.error.HTTPError as error: assert error.code == 403
        for endpoint in ('pause', 'resume-worker', 'run', 'facts', 'settings', 'complete-setup', 'backup'):
            request = urllib.request.Request(base + '/api/' + endpoint, data=b'{}', headers={'X-Hireme-Token': 'fixture-capability'})
            try: urllib.request.urlopen(request); assert False
            except urllib.error.HTTPError as error:
                assert error.code == 403 and 'read-only' in error.read().decode()
        request = urllib.request.Request(base + '/api/export.csv', headers={'X-Hireme-Token': 'fixture-capability'})
        with urllib.request.urlopen(request) as response:
            assert response.headers['Content-Disposition'] == 'attachment; filename="application-ledger.csv"'
            assert b'Cedar Labs' in response.read()
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page()
            page.goto(base + '/#token=fixture-capability')
            expect(page.locator('#demo-banner')).to_be_visible()
            expect(page.locator('#metric-submitted')).to_have_text('2')
            expect(page.locator('#run')).to_be_disabled(); expect(page.locator('#pause')).to_be_disabled()
            assert page.locator('#jobs a[href]').count() == 0
            with page.expect_download() as download:
                page.locator('#export-ledger').click()
            assert download.value.suggested_filename == 'application-ledger.csv'
            assert not download.value.failure()
            browser.close()
    finally: process.terminate(); process.join(5)


def test_unsaved_forms_survive_refresh_and_invalid_aliases_are_actionable(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    root = tmp_path / 'private'
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability')
            page.locator('[data-view=profile]').click()
            field = page.locator('#facts-form [name=full_name]')
            field.fill('Unsaved Candidate'); field.blur()
            page.evaluate('refresh()')
            expect(field).to_have_value('Unsaved Candidate')
            page.locator('[data-view=settings]').click()
            locations = page.locator('#settings-form [name=locations]')
            locations.fill('Unsaved location'); locations.blur()
            page.evaluate('refresh()')
            expect(locations).to_have_value('Unsaved location')
            page.locator('#settings-form [name=company_aliases]').fill('{broken JSON')
            page.get_by_role('button', name='Save preferences', exact=True).click()
            expect(page.locator('#notice')).to_contain_text('Company aliases must be a valid JSON object')
            expect(page.get_by_role('button', name='Save preferences', exact=True)).to_be_enabled()
            expect(locations).to_have_value('Unsaved location')
            page.route('**/api/state*', lambda route: route.abort())
            page.evaluate('refresh()')
            expect(page.locator('#connection-status')).to_be_visible()
            page.unroute('**/api/state*'); page.locator('#retry-connection').click()
            expect(page.locator('#connection-status')).to_be_hidden()
            expect(locations).to_have_value('Unsaved location')
            assert not errors
            browser.close()
    finally: process.terminate(); process.join(5)


def test_essential_facts_optional_toggle_and_provider_fields(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    root = tmp_path / 'private'
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.goto(base + '/#token=fixture-capability')
            page.locator('[data-view=profile]').click()
            expect(page.locator('#facts-form input[name][required]:visible, #facts-form textarea[name][required]:visible')).to_have_count(12)
            expect(page.locator('#facts-form [name=preferred_name]')).to_be_hidden()
            page.locator('#show-optional-facts').check()
            page.locator('#facts-form [name=preferred_name]').fill('Saved in my draft')
            page.locator('#show-optional-facts').uncheck()
            page.evaluate('refresh()')
            page.locator('#show-optional-facts').check()
            expect(page.locator('#facts-form [name=preferred_name]')).to_have_value('Saved in my draft')
            expect(page.locator('[data-draft-for=facts-form]')).to_contain_text('Unsaved changes')
            page.locator('[data-view=providers]').click()
            expect(page.locator('#provider-key-field')).to_be_hidden()
            page.locator('#provider-form [name=provider]').select_option('openai-api')
            expect(page.locator('#provider-key-field')).to_be_visible()
            expect(page.locator('#provider-form [name=provider_model]')).to_have_attribute('required', '')
            page.locator('#provider-form [name=provider_model]').fill('fixture-model')
            page.locator('#provider-form [name=provider_model]').blur()
            page.evaluate('refresh()')
            expect(page.locator('#provider-key-field')).to_be_visible()
            expect(page.locator('#provider-form [name=provider_model]')).to_have_value('fixture-model')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
    finally: process.terminate(); process.join(5)


def test_clearing_optional_fact_stops_reuse_and_survives_reload(store):
    from playwright.sync_api import sync_playwright, expect
    store.put_facts({'preferred_name': 'Previous nickname'})
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page()
            page.goto(base + '/#token=fixture-capability')
            page.locator('[data-view=profile]').click(); page.locator('#show-optional-facts').check()
            field = page.locator('#facts-form [name=preferred_name]')
            expect(field).to_have_value('Previous nickname'); field.fill('')
            page.locator('#confirm-facts').check()
            page.get_by_role('button', name='Save confirmed facts', exact=True).click()
            expect(page.locator('#notice')).to_contain_text('Cleared values will no longer be reused')
            assert 'preferred_name' not in store.facts() and store.settings()['live_enabled']
            page.reload(); page.locator('[data-view=profile]').click(); page.locator('#show-optional-facts').check()
            expect(field).to_have_value('')
            assert store.facts(False)['preferred_name']['source'] == 'revoked'
            browser.close()
    finally: process.terminate(); process.join(5)


def test_opportunity_dialog_and_approved_wording_edits(store, job):
    from playwright.sync_api import sync_playwright, expect
    store.put_template('project', 'I built a Python service and tested every deployment.')
    store.block(job['id'], 'captcha_blocked')
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 390, 'height': 844})
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability')
            details = page.locator('#jobs .opportunity-details').first; details.click()
            expect(page.get_by_role('dialog')).to_be_visible()
            expect(page.locator('#job-dialog-title')).to_have_text(job['title'])
            expect(page.locator('#job-dialog-description')).to_contain_text('Build Python and TypeScript software')
            expect(page.locator('#job-dialog-guidance')).to_contain_text('A CAPTCHA needs you')
            expect(page.locator('#job-dialog-link')).to_have_attribute('href', job['url'])
            expect(page.locator('#close-job-dialog')).to_be_focused()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.keyboard.press('Escape')
            expect(page.get_by_role('dialog')).to_be_hidden(); expect(details).to_be_focused()
            page.locator('[data-view=profile]').click()
            page.locator('#templates summary').click()
            text = page.locator('#templates textarea')
            text.fill('I built a TypeScript service and measured every deployment.')
            text.blur(); page.evaluate('refresh()')
            expect(text).to_have_value('I built a TypeScript service and measured every deployment.')
            page.get_by_role('button', name='Save revised wording', exact=True).click()
            expect(page.locator('#notice')).to_contain_text('Revised wording saved')
            assert store.templates()[0]['revision'] == 2
            page.locator('#templates summary').click()
            page.get_by_role('button', name='Stop using this wording', exact=True).click()
            expect(page.locator('#notice')).to_contain_text('Approved wording withdrawn')
            assert not store.templates()
            assert not errors
            browser.close()
    finally: process.terminate(); process.join(5)


def test_dashboard_backup_download_restores_paused_and_excludes_credentials(store, job, package, tmp_path):
    from playwright.sync_api import sync_playwright, expect
    from hireme.backup import restore_backup
    from hireme.store import Store, worker_lock
    store.prepare(job, package)
    integrations = store.root / 'integrations'; integrations.mkdir(exist_ok=True)
    (integrations / 'provider-key.json').write_text('{"key":"synthetic-do-not-export"}')
    before = store.settings(); generation = store.control_generation()
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        for headers in ({}, {'X-Hireme-Token': 'fixture-capability', 'Origin': 'https://attacker.invalid'}):
            request = urllib.request.Request(base + '/api/backup', data=b'{}', headers=headers)
            try: urllib.request.urlopen(request); assert False
            except urllib.error.HTTPError as error: assert error.code == 403
        with worker_lock(store.root):
            request = urllib.request.Request(base + '/api/backup', data=b'{}', headers={'X-Hireme-Token': 'fixture-capability'})
            try: urllib.request.urlopen(request); assert False
            except urllib.error.HTTPError as error:
                assert error.code == 400 and b'Wait for the active batch' in error.read()
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page()
            page.goto(base + '/#token=fixture-capability'); page.locator('[data-view=settings]').click()
            expect(page.locator('#download-backup')).to_be_enabled()
            with page.expect_download() as download:
                page.locator('#download-backup').click()
            archive = tmp_path / 'download.zip'; download.value.save_as(archive)
            assert download.value.suggested_filename == 'application-history.zip'
            expect(page.locator('#notice')).to_contain_text('History backup downloaded')
            browser.close()
        assert store.settings() == before and store.control_generation() == generation
        restored_root = tmp_path / 'restored'
        restore_backup(archive, restored_root)
        restored = Store(restored_root)
        try:
            assert not restored.settings()['live_enabled']
            assert restored.facts()['email']['value'] == store.facts()['email']['value']
            assert restored.db.execute('SELECT * FROM applications').fetchone()
            assert not (restored_root / 'integrations/provider-key.json').exists()
        finally: restored.close()
    finally: process.terminate(); process.join(5)
