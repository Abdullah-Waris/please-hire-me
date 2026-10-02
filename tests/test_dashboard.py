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
    from hireme import scheduler,worker
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
        req=urllib.request.Request(base+'/api/complete-setup',data=b'{}',headers={'X-Hireme-Token':'fixture-capability','Content-Type':'application/json','Origin':base})
        with urllib.request.urlopen(req) as response:
            assert 'First cycle started' in json.loads(response.read())['message']
        assert queue.get(timeout=5)=='first cycle started'
        assert store.settings()['live_enabled']
    finally:process.terminate();process.join(5);queue.close()
