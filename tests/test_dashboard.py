import json
import multiprocessing
import socket
import time
import urllib.error
import urllib.request
import pytest
from hireme.server import serve
from pathlib import Path


def launch(root,repo,port):
    from hireme import scheduler
    scheduler.status=lambda *args, **kwargs: {'installed':False}
    serve(Path(root),Path(repo),port,token="fixture-capability")


def launch_discovery_fixture(root, repo, port):
    from hireme import opportunity_search
    from hireme.discovery import posting
    def collect(store, net):
        from hireme.discovery import source_result
        store.upsert_job(posting('https://jobs.lever.co/acme/search-fixture', 'Acme', 'Engineer', 'US', 'fixture'))
        source_result(store, 'fixture:healthy', [])
        source_result(store, 'fixture:unavailable', error='Invented source failure')
        for _ in range(500):
            net.checkpoint()
            if (store.root / 'finish-search').exists(): return
            time.sleep(.01)
    opportunity_search.sweep_lists = collect
    opportunity_search.sweep_portals = lambda *args: None
    opportunity_search.sweep_boards = lambda *args, **kwargs: None
    launch(root, repo, port)


def launch_preparation_fixture(root, repo, port):
    import threading
    from hireme import worker
    from hireme.store import Store
    from hireme.util import Blocked
    entered = threading.Event()
    worker.eligible = lambda *args: (100, {})
    class FakeBrowser:
        def __init__(self, store): self.store = store
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def apply(self, job, live=True):
            assert not live
            entered.set()
            for _ in range(500):
                self.store.checkpoint(); time.sleep(.01)
            return 'prepared'
    def run():
        store = Store(Path(root))
        try: worker.cycle(store, Path(repo), discover=False, live=False, browser_factory=FakeBrowser)
        except Blocked: pass
        finally: store.close()
    threading.Thread(target=run, daemon=True).start()
    entered.wait(3)
    launch(root, repo, port)


def launch_worker_failure_fixture(root, repo, port, failure_mode):
    import threading
    from hireme import server, worker
    original_store = server.Store; worker_calls = []; thread_calls = []
    class CloseFailure:
        def __init__(self, store): self.store = store
        def __getattr__(self, key): return getattr(self.store, key)
        def close(self):
            self.store.close()
            raise OSError('synthetic-private-error-detail')
    def store_factory(path):
        if threading.current_thread().name == 'hireme-dashboard-worker':
            worker_calls.append(True)
            if len(worker_calls) == 1 and failure_mode == 'initialize':
                raise PermissionError('synthetic-private-error-detail')
            store = original_store(path)
            return CloseFailure(store) if len(worker_calls) == 1 and failure_mode == 'cleanup' else store
        return original_store(path)
    server.Store = store_factory
    worker.cycle = lambda store, repo: store.event('fixture_dashboard_cycle', 'fixture', {})
    if failure_mode == 'thread-start':
        original_start = threading.Thread.start
        def start(thread):
            if thread.name == 'hireme-dashboard-worker':
                thread_calls.append(True)
                if len(thread_calls) == 1: raise RuntimeError('synthetic-private-error-detail')
            return original_start(thread)
        threading.Thread.start = start
    launch(root, repo, port)


@pytest.mark.parametrize('failure_mode', ['initialize', 'cleanup', 'thread-start'])
def test_dashboard_worker_failure_is_visible_and_retryable(store, failure_mode):
    from playwright.sync_api import sync_playwright, expect
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch_worker_failure_fixture, args=(str(store.root), str(Path.cwd()), port, failure_mode)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 844}); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability')
            expect(page.locator('#run')).to_be_enabled(); page.locator('#run').click()
            for _ in range(50):
                page.evaluate('refresh()')
                if page.locator('#worker-error').is_visible(): break
                page.wait_for_timeout(20)
            expect(page.locator('#worker-error')).to_contain_text('Your last application batch stopped')
            expect(page.locator('#worker-error')).not_to_contain_text('synthetic-private-error-detail')
            expect(page.locator('#run')).to_be_enabled()
            assert not page.request.get(base + '/api/state', headers={'X-Hireme-Token': 'fixture-capability'}).json()['worker_running']
            page.locator('#run').click(); page.evaluate('refresh()')
            expect(page.locator('#worker-error')).to_be_hidden(); expect(page.locator('#run')).to_be_enabled()
            assert store.db.execute("SELECT COUNT(*) FROM events WHERE kind='fixture_dashboard_cycle'").fetchone()[0] == (2 if failure_mode == 'cleanup' else 1)
            assert not store.db.execute('SELECT * FROM applications').fetchone()
            assert not store.db.execute('SELECT * FROM model_requests').fetchone()
            assert not errors and page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
    finally: process.terminate(); process.join(5)


def test_dashboard_stops_preparation_without_resuming_submissions(store, job):
    from playwright.sync_api import sync_playwright, expect
    store.update_settings({'live_enabled': False})
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch_preparation_fixture, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 844}); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability')
            expect(page.locator('#worker-state')).to_have_text('Preparing applications…')
            expect(page.locator('#pause')).to_have_text('Stop preparation & pause')
            expect(page.locator('#pause')).to_be_enabled(); expect(page.locator('#run')).to_be_disabled()
            page.locator('#pause').click(); page.evaluate('refresh()')
            expect(page.locator('#worker-state')).to_have_text('Submissions paused')
            expect(page.locator('#worker-error')).to_be_hidden()
            expect(page.locator('#pause')).to_have_text('Resume')
            assert not store.settings()['live_enabled']
            run = store.db.execute('SELECT * FROM runs').fetchone()
            assert run['status'] == 'paused' and run['submitted'] == 0
            assert json.loads(run['detail'])['mode'] == 'prepare'
            assert not store.db.execute('SELECT * FROM applications').fetchone()
            assert not store.db.execute('SELECT * FROM model_requests').fetchone()
            assert not errors and page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
    finally: process.terminate(); process.join(5)


def test_find_opportunities_and_stop_without_enabling_submissions(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    from hireme.store import Store
    root = tmp_path / 'private'
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch_discovery_fixture, args=(str(root), str(Path(__file__).parent.parent), port))
    process.start(); base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 800}); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability')
            expect(page.locator('#discover')).to_be_enabled()
            expect(page.locator('#run')).to_be_disabled()
            expect(page.locator('#pause')).to_be_disabled()
            assert page.request.post(base + '/api/discover', data={}).status == 403
            page.locator('#discover').click()
            expect(page.locator('#worker-state')).to_have_text('Finding opportunities…')
            expect(page.locator('#discover')).to_be_disabled()
            expect(page.locator('#pause')).to_have_text('Stop search & pause')
            assert page.request.post(base + '/api/discover', data={}, headers={'X-Hireme-Token': 'fixture-capability'}).status == 400
            page.locator('#pause').click()
            page.evaluate('refresh()')
            expect(page.locator('#discover')).to_be_enabled()
            expect(page.locator('#run')).to_be_disabled()
            store = Store(root)
            assert not store.settings()['live_enabled'] and not store.settings()['onboarding_complete']
            assert store.db.execute('SELECT status FROM runs').fetchone()[0] == 'paused'
            expect(page.locator('#worker-error')).to_be_hidden()
            assert store.db.execute('SELECT COUNT(*) FROM applications').fetchone()[0] == 0
            (root / 'finish-search').touch()
            page.locator('#discover').click()
            page.evaluate('refresh()')
            expect(page.locator('#discover')).to_be_enabled()
            expect(page.locator('#runs')).to_contain_text('Opportunity search')
            expect(page.locator('#runs')).to_contain_text('No submissions')
            expect(page.locator('#runs')).to_contain_text('2 sources checked · 1 unavailable')
            assert not store.settings()['live_enabled']
            assert store.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 1
            assert store.db.execute('SELECT COUNT(*) FROM model_requests').fetchone()[0] == 0
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors
            store.close(); browser.close()
    finally:
        process.terminate(); process.join(5)


def test_question_pages_keep_old_employer_context_and_protect_unsaved_answers(store, job):
    from playwright.sync_api import sync_playwright, expect
    from hireme.util import digest
    special = store.ask(job['id'], job['host'], 'Café 100%_ question', [])
    for index in range(30): store.ask(job['id'], job['host'], f'Core prompt {index}', [])
    for index in range(501):
        extra = {**job, 'id': digest(f'question-job-{index}'), 'url': job['url'] + f'-{index}', 'company': f'Other employer {index}'}
        store.upsert_job(extra); store.db.execute('UPDATE jobs SET score=100 WHERE id=?', (extra['id'],))
        store.ask(extra['id'], extra['host'], f'Aux prompt {index}', [])
    bad = store.ask(job['id'], job['host'], 'BadChoices', [])
    store.db.execute('UPDATE questions SET options=? WHERE id=?', ('not json', bad))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 844}); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability'); page.locator('[data-view=questions]').click()
            expect(page.locator('#question-list form')).to_have_count(25)
            expect(page.locator('#question-page')).to_contain_text('1–25 of 533')
            snapshot = page.request.get(base + '/api/state', headers={'X-Hireme-Token': 'fixture-capability'}).json()
            assert len(snapshot['questions']) == 50 and snapshot['summary']['question_count'] == 533
            assert job['id'] not in {row['id'] for row in snapshot['jobs']}
            assert page.request.get(base + '/api/questions').status == 403
            expect(page.locator('#question-list')).to_contain_text('Acme')
            field = page.locator('#question-list textarea').first
            field.fill('Unfinished synthetic answer'); field.blur(); page.evaluate('refresh()')
            expect(field).to_have_value('Unfinished synthetic answer')
            expect(page.locator('#question-search')).to_be_disabled(); expect(page.locator('#question-next')).to_be_disabled()
            page.locator('#question-list [data-question-discard]').first.click()
            expect(page.locator('#question-next')).to_be_enabled()
            page.route('**/api/questions*', lambda route: route.fulfill(status=503, json={'error': 'Synthetic temporary failure'}))
            page.locator('#question-search').fill('Core prompt')
            expect(page.locator('#question-error')).to_contain_text('Synthetic temporary failure')
            page.unroute('**/api/questions*'); page.locator('#question-retry').click()
            expect(page.locator('#question-page')).to_contain_text('1–25 of 30')
            page.locator('#question-next').click()
            expect(page.locator('#question-page')).to_contain_text('26–30 of 30')
            expect(page.locator('#question-list')).to_be_focused()
            page.locator('#question-search').fill('CAFÉ 100%_')
            expect(page.locator('#question-list form')).to_have_count(1)
            expect(page.locator('#question-list')).to_contain_text('Acme')
            page.locator('#question-list textarea').fill('Synthetic confirmed response')
            page.locator('#question-list button[type=submit], #question-list button:not([type])').click()
            expect(page.locator('#question-page')).to_contain_text('0 unanswered questions')
            assert store.saved_answer(job['host'], 'Café 100%_ question', [])['value'] == 'Synthetic confirmed response'
            page.locator('#question-search').fill('BadChoices')
            expect(page.locator('#question-list')).to_contain_text('invalid choices')
            expect(page.locator('#question-list form')).to_have_count(0)
            assert not errors and page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
    finally: process.terminate(); process.join(5)


def test_unresolved_outcome_pages_preserve_old_context_and_require_explicit_verification(store, job):
    from playwright.sync_api import sync_playwright, expect
    from hireme.util import digest
    from tests.test_outcome_ledger import insert_outcome
    store.db.execute("UPDATE jobs SET company=?,status='unknown' WHERE id=?", ('Café 100%_ Labs', job['id']))
    insert_outcome(store, 'old-uncertain', job['id'], stamp='2000-01-01T00:00:00+00:00')
    for index in range(510):
        extra = {**job, 'id': digest(f'outcome-job-{index}'), 'url': job['url'] + f'-outcome-{index}', 'company': f'Other employer {index}'}
        store.upsert_job(extra); store.db.execute("UPDATE jobs SET score=100,status='unknown' WHERE id=?", (extra['id'],))
        insert_outcome(store, f'outcome-{index:03}', extra['id'], 'unknown' if index % 2 else 'awaiting_verification')
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 844}); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability'); page.locator('[data-view=questions]').click()
            expect(page.locator('#uncertain form')).to_have_count(25)
            expect(page.locator('#outcome-page')).to_contain_text('1–25 of 511')
            expect(page.locator('#uncertain')).to_contain_text('Café 100%_ Labs')
            snapshot = page.request.get(base + '/api/state', headers={'X-Hireme-Token': 'fixture-capability'}).json()
            assert job['id'] not in {row['id'] for row in snapshot['jobs']}
            assert 'old-uncertain' not in {row['id'] for row in snapshot['applications']}
            assert page.request.get(base + '/api/outcomes').status == 403
            data = page.request.get(base + '/api/outcomes', headers={'X-Hireme-Token': 'fixture-capability'}).json()
            assert all('package' not in row for row in data['applications'])
            field = page.locator('#uncertain textarea').first
            field.fill('Unfinished synthetic verification'); field.blur(); page.evaluate('refresh()')
            expect(field).to_have_value('Unfinished synthetic verification')
            expect(page.locator('#outcome-search')).to_be_disabled(); expect(page.locator('#outcome-filter')).to_be_disabled()
            expect(page.locator('#outcome-next')).to_be_disabled()
            page.locator('#uncertain [data-outcome-discard]').first.click()
            page.locator('#outcome-next').click(); expect(page.locator('#outcome-page')).to_contain_text('26–50 of 511')
            expect(page.locator('#uncertain')).to_be_focused()
            page.route('**/api/outcomes*', lambda route: route.fulfill(status=503, json={'error': 'Synthetic outcome load failure'}))
            page.locator('#outcome-search').fill('CAFÉ 100%_')
            expect(page.locator('#outcome-error')).to_contain_text('Synthetic outcome load failure')
            page.unroute('**/api/outcomes*'); page.locator('#outcome-retry').click()
            expect(page.locator('#uncertain form')).to_have_count(1)
            page.locator('#uncertain textarea').fill('Synthetic employer portal confirms no submission occurred')
            page.locator('#uncertain button:not([type])').click()
            assert store.db.execute("SELECT state FROM applications WHERE id='old-uncertain'").fetchone()[0] == 'unknown'
            expect(page.locator('#uncertain select')).to_have_value('')
            page.locator('#uncertain select').select_option('false')
            page.locator('#uncertain button:not([type])').click()
            expect(page.locator('#outcome-page')).to_contain_text('0 unresolved outcomes')
            assert store.db.execute("SELECT state FROM applications WHERE id='old-uncertain'").fetchone()[0] == 'not_submitted'
            assert store.db.execute('SELECT status FROM jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'not_submitted'
            assert store.settings()['live_enabled']
            page.locator('#outcome-search').fill(''); page.locator('#outcome-filter').select_option('awaiting_verification')
            expect(page.locator('#outcome-page')).to_contain_text('of 255')
            assert not errors and page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
    finally: process.terminate(); process.join(5)


def test_outcome_evidence_loads_only_on_request_retries_and_preserves_reading_focus(store, job, package):
    from playwright.sync_api import sync_playwright, expect
    aid = store.prepare(job, package); store.begin_submit(aid); store.finish(aid, 'unknown')
    store.db.execute('UPDATE applications SET confirmation=? WHERE id=?', ('<Synthetic recorded portal note>', aid))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 844}); errors = []; requests = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append(request.url) if '/api/application/' in request.url else None)
            page.goto(base + '/#token=fixture-capability'); page.locator('[data-view=questions]').click()
            expect(page.locator('#uncertain form')).to_have_count(1)
            assert not requests
            page.route('**/api/application/' + aid, lambda route: route.fulfill(status=503, json={'error': 'Synthetic evidence failure'}))
            summary = page.locator('#uncertain details > summary')
            summary.click()
            expect(page.locator('#uncertain')).to_contain_text('Synthetic evidence failure')
            page.unroute('**/api/application/' + aid)
            page.get_by_role('button', name='Retry evidence', exact=True).click()
            expect(page.locator('#uncertain .answer-log')).to_contain_text('test@candidate.invalid')
            expect(page.locator('#uncertain details')).to_contain_text('<Synthetic recorded portal note>')
            assert len(requests) == 2
            summary.focus(); page.evaluate('refresh()')
            expect(summary).to_be_focused(); expect(page.locator('#uncertain details')).to_have_attribute('open', '')
            assert len(requests) == 2
            store.db.execute('UPDATE applications SET updated=? WHERE id=?', ('2026-10-04T00:00:00+00:00', aid))
            page.evaluate('refresh()')
            expect(summary).to_be_focused(); expect(page.locator('#uncertain .answer-log')).to_contain_text('test@candidate.invalid')
            assert len(requests) == 3
            assert not errors and page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
    finally: process.terminate(); process.join(5)


def test_compact_holds_preview_opens_complete_ledger_and_keeps_controls_stable(store, job):
    from playwright.sync_api import sync_playwright, expect
    from hireme.util import digest
    store.db.execute("UPDATE jobs SET status='blocked',reason='captcha' WHERE id=?", (job['id'],))
    for index in range(500):
        extra = {**job, 'id': digest(f'held-job-{index}'), 'url': job['url'] + f'-held-{index}', 'company': f'Other held employer {index}'}
        store.upsert_job(extra); store.db.execute("UPDATE jobs SET score=100,status='blocked',reason='captcha' WHERE id=?", (extra['id'],))
    quiet = {**job, 'id': digest('quiet-held-job'), 'url': job['url'] + '-quiet', 'company': 'Quiet Company'}
    store.upsert_job(quiet); store.db.execute("UPDATE jobs SET status='blocked',reason='company_blocked' WHERE id=?", (quiet['id'],))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 844}); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability'); page.locator('[data-view=questions]').click()
            expect(page.locator('#blocked-scope')).to_contain_text('Showing 12 of 501')
            expect(page.locator('#blocked-jobs .opportunity-details')).to_have_count(12)
            button = page.locator('#blocked-jobs .opportunity-details').first
            button.evaluate("element => element.dataset.fixtureStable = 'yes'")
            button.focus(); page.evaluate('refresh()')
            expect(button).to_be_focused(); expect(button).to_have_attribute('data-fixture-stable', 'yes')
            page.locator('#view-all-holds').click()
            expect(page.locator('#heading')).to_have_text('Today’s applications')
            expect(page.locator('#status-filter')).to_have_value('blocked')
            expect(page.locator('#ledger-page-label')).to_contain_text('1–50 of 501')
            page.locator('#job-search').fill('Acme')
            expect(page.locator('#jobs .opportunity-details')).to_have_count(1)
            expect(page.locator('#jobs')).to_contain_text('Acme')
            assert not errors and page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
    finally: process.terminate(); process.join(5)


def test_model_request_budget_counts_all_providers_without_replacing_connection_drafts(store):
    from datetime import datetime, timedelta, timezone
    from playwright.sync_api import sync_playwright, expect
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    store.update_settings({'max_model_requests_per_day': 2, 'max_model_requests_per_cycle': 2})
    for provider in ('claude-cli', 'openai-api'):
        store.db.execute('INSERT INTO model_requests(timestamp,run_id,provider) VALUES(?,?,?)', (stamp, 'fixture-run', provider))
    store.db.execute('INSERT INTO model_requests(timestamp,run_id,provider) VALUES(?,?,?)',
                     ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec='seconds'), 'old-run', 'codex-cli'))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 844}); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability'); page.locator('[data-view=providers]').click()
            expect(page.locator('#model-request-usage')).to_contain_text('2 of 2 requests used today · 0 remaining · Daily cap reached')
            expect(page.locator('#model-request-reset')).to_contain_text(store.settings()['timezone'])
            page.locator('#provider-form [name=provider]').select_option('openai-api')
            page.locator('#provider-form [name=provider_model]').fill('Synthetic unsaved model')
            page.locator('#provider-form [name=key]').fill('synthetic-unsaved-key')
            page.locator('#provider-form [name=key]').blur()
            store.db.execute('INSERT INTO model_requests(timestamp,run_id,provider) VALUES(?,?,?)', (stamp, 'fixture-run', 'codex-cli'))
            page.evaluate('refresh()')
            expect(page.locator('#model-request-usage')).to_contain_text('3 of 2 requests used today · 0 remaining')
            expect(page.locator('#provider-form [name=provider_model]')).to_have_value('Synthetic unsaved model')
            expect(page.locator('#provider-form [name=key]')).to_have_value('synthetic-unsaved-key')
            assert not errors and page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
    finally: process.terminate(); process.join(5)


def test_complete_batch_history_pages_searches_old_notes_and_retries(store):
    for index in range(61):
        store.db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?)',
                         (f'run-{index:03}', '2026-10-03T12:00:00+00:00', None, 'finished', 0,
                          json.dumps({'mode': 'prepare', 'confirmed': 2, 'attempts': 2}) if index == 0 else '{}'))
    store.db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?)',
                     ('old-blocked', '2000-01-01T00:00:00+00:00', None, 'blocked', 0, json.dumps({'reason': 'Café 100%_ synthetic blocker'})))
    store.db.execute('INSERT INTO model_requests(timestamp,run_id,provider) VALUES(?,?,?)',
                     ('2000-01-01T00:00:00+00:00', 'old-blocked', 'claude-cli'))
    from playwright.sync_api import sync_playwright, expect
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 844}); errors = []; history_requests = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: history_requests.append(request.url) if '/api/runs' in request.url else None)
            page.goto(base + '/#token=fixture-capability')
            expect(page.locator('#runs .run-row')).to_have_count(5)
            expect(page.locator('#runs')).to_contain_text('Preparation batch · 2 prepared')
            expect(page.locator('#runs')).not_to_contain_text('2 submitted')
            assert not history_requests
            assert page.request.get(base + '/api/runs').status == 403
            page.locator('#run-history-panel > summary').click()
            expect(page.locator('#run-history .run-row')).to_have_count(25)
            expect(page.locator('#run-history-page')).to_contain_text('1–25 of 62')
            page.locator('#run-history-next').click(); expect(page.locator('#run-history-page')).to_contain_text('26–50 of 62')
            expect(page.locator('#run-history')).to_be_focused()
            page.locator('#run-history-next').click(); expect(page.locator('#run-history-page')).to_contain_text('51–62 of 62')
            expect(page.locator('#run-history')).to_contain_text('Café 100%_ synthetic blocker')
            expect(page.locator('#run-history')).to_contain_text('1 model request')
            page.route('**/api/runs*', lambda route: route.fulfill(status=503, json={'error': 'Synthetic history unavailable'}))
            page.locator('#run-search').fill('CAFÉ 100%_')
            expect(page.locator('#run-history-error')).to_contain_text('Synthetic history unavailable')
            page.unroute('**/api/runs*'); page.locator('#run-history-retry').click()
            expect(page.locator('#run-history .run-row')).to_have_count(1)
            expect(page.locator('#run-history-page')).to_contain_text('1–1 of 1')
            page.locator('#run-filter').select_option('finished')
            expect(page.locator('#run-history-page')).to_contain_text('0 recorded batches')
            page.locator('#run-search').fill('')
            expect(page.locator('#run-history-page')).to_contain_text('of 61')
            assert not errors and page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
    finally: process.terminate(); process.join(5)


def test_complete_source_health_search_pages_retry_and_mobile_layout(store):
    for index in range(110):
        store.db.execute('INSERT INTO sources VALUES(?,?,?,?,?)',
                         (f'source-{index:03}', 'ok', '2026-10-03T12:00:00+00:00', '', '{}'))
    store.db.execute('INSERT INTO sources VALUES(?,?,?,?,?)',
                     ('old-Café-100%_', 'error', '2000-01-01T00:00:00+00:00', '<script>synthetic timeout</script>', '{}'))
    from playwright.sync_api import sync_playwright, expect
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 844}); errors = []; requests = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append(request.url) if '/api/sources' in request.url else None)
            page.goto(base + '/#token=fixture-capability')
            expect(page.locator('#jobs')).to_contain_text('Your next chapter starts here')
            assert not requests and page.request.get(base + '/api/sources').status == 403
            page.locator('#source-health-panel > summary').click()
            expect(page.locator('#sources .source-health-row')).to_have_count(25)
            expect(page.locator('#source-health-summary')).to_have_text('111 sources checked · 110 available · 1 unavailable')
            expect(page.locator('#sources')).to_contain_text('<script>synthetic timeout</script>')
            assert page.locator('#sources script').count() == 0
            page.locator('#source-health-next').click()
            expect(page.locator('#source-health-page')).to_contain_text('26–50 of 111')
            expect(page.locator('#sources')).to_be_focused()
            page.locator('#source-search').fill('source-109')
            expect(page.locator('#source-health-page')).to_contain_text('1–1 of 1')
            expect(page.locator('#sources')).to_contain_text('source-109')
            page.locator('#source-search').fill('')
            expect(page.locator('#source-health-page')).to_contain_text('1–25 of 111')
            page.locator('#source-filter').select_option('error')
            expect(page.locator('#source-health-page')).to_contain_text('1–1 of 1')
            expect(page.locator('#sources')).to_contain_text('Unavailable')
            page.route('**/api/sources*', lambda route: route.fulfill(status=503, json={'error': 'Synthetic source checks unavailable'}))
            page.locator('#source-search').fill('CAFÉ-100%_')
            expect(page.locator('#source-health-error')).to_contain_text('Synthetic source checks unavailable')
            page.unroute('**/api/sources*'); page.locator('#source-health-retry').click()
            expect(page.locator('#source-health-error')).to_be_hidden()
            expect(page.locator('#sources .source-health-row')).to_have_count(1)
            page.locator('#source-filter').select_option('ok')
            expect(page.locator('#source-health-page')).to_have_text('0 sources')
            expect(page.locator('#source-health-summary')).to_contain_text('111 sources checked')
            assert not errors and page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
    finally: process.terminate(); process.join(5)


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
    store.update_settings({'cycle_timeout_seconds': 30})
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
            expect(page.locator('[name="cycle_timeout_seconds"]')).to_have_value('0.5')
            expect(page.locator('[name="employer_accounts"]')).not_to_be_checked()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.locator('[name="employer_accounts"]').check()
            captures=tmp_path/'ui';captures.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(captures/'employer-preferences-mobile.png'))
            page.get_by_role('button',name='Save preferences',exact=True).click()
            expect(page.locator('#notice')).to_contain_text('Search preferences saved')
            assert store.settings()['employer_accounts'] is True
            assert store.settings()['cycle_timeout_seconds'] == 30
            page.locator('[name="cycle_timeout_seconds"]').fill('2.5')
            page.get_by_role('button',name='Save preferences',exact=True).click()
            expect(page.locator('#notice')).to_contain_text('Search preferences saved')
            assert store.settings()['cycle_timeout_seconds'] == 150
            assert not store.settings()['live_enabled']
            page.locator('[data-view="profile"]').click()
            page.locator('#facts-form [name="full_name"]').fill('Unsaved synthetic name')
            from hireme.store import worker_lock
            with worker_lock(root):
                page.locator('#withdraw-transcript').click()
                expect(page.locator('#notice')).to_contain_text('Wait for the active batch to finish')
                assert store.db.execute("SELECT hash FROM documents WHERE kind='transcript'").fetchone()[0] == updated
            page.locator('#withdraw-transcript').click()
            expect(page.locator('#transcript-state')).to_contain_text('No transcript imported')
            expect(page.locator('#withdraw-transcript')).to_be_hidden()
            expect(page.locator('#transcript-upload')).to_be_focused()
            expect(page.locator('#facts-form [name="full_name"]')).to_have_value('Unsaved synthetic name')
            assert not store.db.execute("SELECT 1 FROM documents WHERE kind='transcript'").fetchone()
            assert (root/'documents'/(updated+'.pdf')).is_file()
            assert not store.settings()['live_enabled']
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
    scheduler.status=lambda *args, **kwargs: {'installed':False}
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
    import hireme.scheduler
    hireme.scheduler.status=lambda *args, **kwargs: {'installed':False}
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
            page.locator('#settings-form [name=seniority]').fill('internship');page.locator('#settings-form [name=max_attempts_per_cycle]').fill('2');page.locator('#settings-form button[type=submit]').click();expect(page.locator('#notice')).to_contain_text('Search preferences saved')
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
        for endpoint in ('pause', 'resume-worker', 'run', 'discover', 'facts', 'settings', 'complete-setup', 'backup', 'recover', 'answer-revoke', 'schedule-apply', 'company-skip', 'company-allow'):
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
            expect(page.locator('#runs')).to_contain_text('2 sources checked · 1 unavailable')
            expect(page.locator('#run')).to_be_disabled(); expect(page.locator('#pause')).to_be_disabled()
            assert page.locator('#jobs a[href]').count() == 0
            with page.expect_download() as download:
                page.locator('#export-ledger').click()
            assert download.value.suggested_filename == 'application-ledger.csv'
            assert not download.value.failure()
            browser.close()
    finally: process.terminate(); process.join(5)


def launch_schedule_fixture(root, repo, port):
    from hireme import scheduler
    def fixture_status(store=None, **kwargs):
        row = store.db.execute("SELECT detail FROM events WHERE kind='schedule_installed' ORDER BY seq DESC LIMIT 1").fetchone()
        return {'installed': True, 'matches_applicant': True, 'interval_hours': json.loads(row[0])['interval_hours'] if row else 6}
    scheduler.status = fixture_status
    scheduler.install = lambda store, repo: 'synthetic schedule; no OS services changed'
    serve(Path(root), Path(repo), port, token='fixture-capability')


def test_dashboard_applies_saved_schedule_without_resuming_and_protects_drafts(store):
    from playwright.sync_api import sync_playwright, expect
    store.update_settings({'live_enabled': False, 'schedule_hours': 6})
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch_schedule_fixture, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        try: urllib.request.urlopen(base + '/api/schedule'); assert False
        except urllib.error.HTTPError as error: assert error.code == 403
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.goto(base + '/#token=fixture-capability')
            expect(page.locator('#worker-state')).to_have_text('Submissions paused')
            page.locator('[data-view=settings]').click()
            expect(page.locator('#schedule-state')).to_contain_text('Installed interval: 6 hours')
            page.locator('#settings-form [name=schedule_hours]').fill('3')
            expect(page.locator('#apply-schedule')).to_be_disabled()
            expect(page.locator('#schedule-state')).to_contain_text('Save your pending preferences')
            page.locator('#settings-form button[type=submit]').click()
            expect(page.locator('#notice')).to_contain_text('Search preferences saved')
            expect(page.locator('#schedule-state')).to_contain_text('Saved interval: 3 hours')
            page.locator('#apply-schedule').click()
            expect(page.locator('#notice')).to_contain_text('Schedule applied: every 3 hours')
            expect(page.locator('#schedule-state')).to_contain_text('Installed interval: 3 hours')
            assert not store.settings()['live_enabled'] and not store.db.execute('SELECT * FROM runs').fetchone()
            page.route('**/api/schedule', lambda route: route.fulfill(json={'installed': True, 'matches_applicant': False, 'interval_hours': 2}))
            page.locator('#check-schedule').click()
            expect(page.locator('#schedule-state')).to_contain_text('another applicant')
            expect(page.locator('#apply-schedule')).to_be_disabled()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
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
            page.locator('#alias-json-toggle').click()
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


def test_company_name_editor_preserves_drafts_and_round_trips_json(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    from hireme.store import Store
    root = tmp_path / 'private'; store = Store(root)
    store.update_settings({'company_aliases': {'Acme Inc': 'Acme'}})
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 800}); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability'); page.locator('[data-view=settings]').click()
            expect(page.locator('[data-alias-other]')).to_have_value('Acme Inc')
            expect(page.locator('[data-alias-main]')).to_have_value('Acme')
            expect(page.locator('#alias-json-field')).to_be_hidden()
            page.locator('#add-company-alias').click()
            rows = page.locator('.company-alias-row')
            expect(rows).to_have_count(2)
            rows.nth(1).locator('[data-alias-other]').fill('Beta LLC')
            rows.nth(1).locator('[data-alias-main]').fill('Beta'); rows.nth(1).locator('[data-alias-main]').blur()
            page.evaluate('refresh()')
            expect(rows.nth(1).locator('[data-alias-other]')).to_have_value('Beta LLC')
            expect(page.locator('[data-draft-for=settings-form]')).to_contain_text('Unsaved changes')
            page.get_by_role('button', name='Save preferences', exact=True).click()
            expect(page.locator('#notice')).to_contain_text('Search preferences saved')
            assert store.settings()['company_aliases'] == {'Acme Inc': 'Acme', 'Beta LLC': 'Beta'}
            page.locator('#alias-json-toggle').click()
            page.locator('#alias-json-field textarea').fill('{"Acme Inc":"Acme", "Beta LLC":"Beta", "Gamma Inc":"Gamma"}')
            page.locator('#alias-json-toggle').click()
            expect(rows).to_have_count(3)
            expect(rows.nth(2).locator('[data-alias-main]')).to_have_value('Gamma')
            rows.nth(2).locator('[data-alias-other]').fill('ACME, Inc.')
            page.get_by_role('button', name='Save preferences', exact=True).click()
            expect(page.locator('#notice')).to_contain_text('repeats another alternate name')
            assert len(store.settings()['company_aliases']) == 2
            rows.nth(2).get_by_role('button', name='Remove alternate name ACME, Inc.').click()
            expect(page.locator('#add-company-alias')).to_be_focused()
            rows.nth(1).get_by_role('button', name='Remove alternate name Beta LLC').click()
            page.get_by_role('button', name='Save preferences', exact=True).click()
            expect(page.locator('#notice')).to_have_text('Search preferences saved.')
            assert store.settings()['company_aliases'] == {'Acme Inc': 'Acme'}
            assert not store.settings()['live_enabled']
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth') and not errors
            browser.close()
    finally:
        store.close(); process.terminate(); process.join(5)


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
            page.locator('#provider-form [name=key]').fill('synthetic-unused-provider-key')
            page.locator('#provider-form [name=provider_model]').fill('invalid model with spaces')
            page.locator('#provider-form button[type=submit]').click()
            expect(page.locator('#notice')).to_contain_text('Use a model ID')
            assert not (root / 'integrations/provider-key.json').exists()
            page.locator('#provider-form [name=provider]').select_option('codex-cli')
            page.locator('#provider-form [name=provider_model]').fill('')
            page.locator('#provider-form button[type=submit]').click()
            expect(page.locator('#notice')).to_contain_text('Connection saved')
            assert not (root / 'integrations/provider-key.json').exists()
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
    job['description'] += '\n' + 'Synthetic long posting text for scrolling verification. ' * 150
    store.upsert_job(job)
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
            page.locator('#job-dialog').evaluate('(dialog)=>dialog.scrollTop=dialog.scrollHeight')
            expect(page.locator('#close-job-dialog')).to_be_in_viewport()
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


def test_full_ledger_search_and_pagination_preserve_old_evidence(store):
    from playwright.sync_api import sync_playwright, expect
    from hireme.discovery import posting
    for index in range(520):
        item = posting(f'https://jobs.lever.co/full-ledger/req-{index}', f'Company {index}', 'Software Intern', 'US', 'fixture')
        store.upsert_job(item)
        store.db.execute("UPDATE jobs SET score=90,status='confirmed' WHERE id=?", (item['id'],))
        store.db.execute('''INSERT INTO applications
            (id,job_id,company_key,state,package,hash,created,updated,attempted)
            VALUES(?,?,?,?,?,?,?,?,?)''',
            (f'new-{index}', item['id'], store.company(item['company']), 'confirmed', '{"answers":[]}', 'fixture',
             '2026-10-02T12:00:00+00:00', '2026-10-02T12:00:00+00:00', '2026-10-02T12:00:00+00:00'))
    old = posting('https://jobs.lever.co/full-ledger/old', 'Café 100%', 'Research Intern', 'Remote (US)', 'fixture')
    store.upsert_job(old)
    store.db.execute("UPDATE jobs SET status='confirmed',first_seen='2020-01-01T00:00:00+00:00' WHERE id=?", (old['id'],))
    store.db.execute('''INSERT INTO applications
        (id,job_id,company_key,state,package,hash,created,updated,attempted) VALUES(?,?,?,?,?,?,?,?,?)''',
        ('old-record', old['id'], store.company(old['company']), 'confirmed',
         json.dumps({'answers': [{'field': {'label': 'Historic answer'}, 'value': 'Synthetic historic answer', 'provenance': {}}]}),
         'fixture', '2020-01-01T00:00:00+00:00', '2020-01-01T00:00:00+00:00', '2020-01-01T00:00:00+00:00'))
    assert old['id'] not in {item['id'] for item in store.snapshot()['jobs']}
    assert 'old-record' not in {item['id'] for item in store.snapshot()['applications']}
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        try: urllib.request.urlopen(base + '/api/jobs'); assert False
        except urllib.error.HTTPError as error: assert error.code == 403
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability')
            expect(page.locator('#jobs tbody tr')).to_have_count(50)
            expect(page.locator('#ledger-page-label')).to_contain_text('1–50 of 521')
            page.locator('#ledger-next').click()
            expect(page.locator('#ledger-page-label')).to_contain_text('51–100 of 521')
            expect(page.locator('#jobs')).to_be_focused()
            page.locator('#ledger-previous').click()
            expect(page.locator('#ledger-page-label')).to_contain_text('1–50 of 521')
            page.locator('#job-search').fill('CAFÉ')
            expect(page.locator('#jobs tbody tr')).to_have_count(1)
            expect(page.locator('#jobs')).to_contain_text('Café 100%')
            expect(page.locator('#ledger-next')).to_be_disabled()
            page.locator('#jobs').get_by_text('Answers & evidence', exact=True).click()
            expect(page.locator('#jobs')).to_contain_text('Synthetic historic answer')
            page.locator('#job-search').fill('100%')
            expect(page.locator('#jobs tbody tr')).to_have_count(1)
            assert not errors
            browser.close()
    finally: process.terminate(); process.join(5)


def test_dashboard_recovers_crashed_worker_and_refuses_live_recovery(store, job, package):
    from playwright.sync_api import sync_playwright, expect
    from hireme.store import worker_lock
    application = store.prepare(job, package); store.begin_submit(application)
    store.db.execute("INSERT INTO runs(id,started,status) VALUES('interrupted-run','2020-01-01T00:00:00+00:00','running')")
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with worker_lock(store.root):
            request = urllib.request.Request(base + '/api/recover', data=b'{}', headers={'X-Hireme-Token': 'fixture-capability'})
            try: urllib.request.urlopen(request); assert False
            except urllib.error.HTTPError as error:
                assert error.code == 400 and b'A batch is still running' in error.read()
            assert store.settings()['live_enabled']
            assert store.db.execute('SELECT state FROM applications WHERE id=?', (application,)).fetchone()[0] == 'submitting'
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page()
            page.goto(base + '/#token=fixture-capability')
            expect(page.locator('#recovery-banner')).to_be_visible()
            expect(page.locator('#run')).to_be_disabled()
            page.locator('#recover-worker').click()
            expect(page.locator('#notice')).to_contain_text('Applications remain paused')
            expect(page.locator('#recovery-banner')).to_be_hidden()
            expect(page.locator('#pause')).to_have_text('Resume')
            assert not store.settings()['live_enabled']
            assert store.db.execute('SELECT state FROM applications WHERE id=?', (application,)).fetchone()[0] == 'unknown'
            page.locator('[data-view=questions]').click()
            expect(page.locator('#uncertain')).to_contain_text('Acme')
            browser.close()
    finally: process.terminate(); process.join(5)


def test_saved_answers_review_withdrawal_and_restricted_browser_storage(store, job):
    from playwright.sync_api import sync_playwright, expect
    qid = store.ask(job['id'], job['host'], 'Café 100% <synthetic> question', [])
    store.answer_question(qid, 'Synthetic previously confirmed response')
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        try: urllib.request.urlopen(base + '/api/saved-answers'); assert False
        except urllib.error.HTTPError as error: assert error.code == 403
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 844}); errors = []
            page.add_init_script("Object.defineProperty(window, 'sessionStorage', {get() {throw new DOMException('Storage denied', 'SecurityError')}})")
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability')
            page.locator('[data-view=profile]').click()
            page.locator('#saved-answers-panel > summary').click()
            assert not errors, errors
            expect(page.locator('#answers-page')).to_contain_text('1–1 of 1')
            page.locator('#answer-search').fill('CAFÉ 100%')
            expect(page.locator('#saved-answers')).to_contain_text('Café 100% <synthetic> question')
            page.locator('#saved-answers summary').click()
            expect(page.locator('#saved-answers')).to_contain_text('Synthetic previously confirmed response')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#saved-answers button').click()
            expect(page.locator('#notice')).to_contain_text('Saved answer withdrawn')
            expect(page.locator('#answers-page')).to_contain_text('0 saved answers')
            expect(page.locator('#saved-answers')).to_be_focused()
            assert store.saved_answer(job['host'], 'Café 100% <synthetic> question', []) is None
            assert not errors and '#' not in page.url
            browser.close()
    finally: process.terminate(); process.join(5)


def test_company_shortcut_preserves_preference_drafts_and_shows_dialog_errors(store, job):
    from playwright.sync_api import sync_playwright, expect
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 844}); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability')
            expect(page.locator('#jobs .opportunity-details')).to_have_count(1)
            page.locator('[data-view=settings]').click()
            page.locator('#settings-form [name=locations]').fill('San Francisco')
            page.locator('[data-view=today]').click()
            page.locator('#jobs .opportunity-details').click()
            expect(page.locator('#skip-job-company')).to_be_disabled()
            expect(page.locator('#skip-company-help')).to_contain_text('Save your pending preferences')
            page.keyboard.press('Escape')
            page.locator('[data-view=settings]').click()
            expect(page.locator('#settings-form [name=locations]')).to_have_value('San Francisco')
            page.locator('#settings-form button[type=submit]').click()
            expect(page.locator('#notice')).to_contain_text('Search preferences saved')
            page.locator('[data-view=today]').click()
            page.locator('#jobs .opportunity-details').click()
            page.route('**/api/company-skip', lambda route: route.fulfill(status=400, json={'error': 'Synthetic failure; try again'}))
            page.locator('#skip-job-company').click()
            expect(page.locator('#skip-company-help')).to_contain_text('Synthetic failure')
            expect(page.locator('#skip-job-company')).to_be_enabled()
            page.unroute('**/api/company-skip')
            page.locator('#skip-job-company').click()
            expect(page.locator('#job-dialog')).not_to_be_visible()
            expect(page.locator('#notice')).to_contain_text('Future applications at Acme are skipped')
            expect(page.locator('#jobs')).to_contain_text('Not a match')
            expect(page.locator('#heading')).to_be_focused()
            assert store.settings()['skip_companies'] == ['Acme']
            page.locator('#jobs .opportunity-details').click()
            expect(page.locator('#skip-job-company')).to_have_text('Include this company again')
            expect(page.locator('#skip-job-company')).to_be_enabled()
            assert page.request.post(base + '/api/company-allow', data={'id': job['id']}).status == 403
            page.route('**/api/company-allow', lambda route: route.fulfill(status=400, json={'error': 'Synthetic inclusion failure'}))
            page.locator('#skip-job-company').click()
            expect(page.locator('#skip-company-help')).to_contain_text('Synthetic inclusion failure')
            assert store.settings()['skip_companies'] == ['Acme']
            page.unroute('**/api/company-allow')
            page.locator('#skip-job-company').click()
            expect(page.locator('#job-dialog')).not_to_be_visible()
            expect(page.locator('#notice')).to_contain_text('Acme is no longer excluded')
            assert store.settings()['skip_companies'] == []
            assert store.db.execute('SELECT COUNT(*) FROM applications').fetchone()[0] == 0
            assert store.db.execute('SELECT reason FROM jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'company_blocked'
            page.locator('#jobs .opportunity-details').click()
            expect(page.locator('#skip-job-company')).to_have_text('Skip this company')
            assert not errors and page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
    finally: process.terminate(); process.join(5)


def test_record_evidence_loads_on_demand_retries_and_stays_open_after_refresh(store, job, package):
    from playwright.sync_api import sync_playwright, expect
    aid = store.prepare(job, package); store.begin_submit(aid); store.finish(aid, 'unknown')
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        try: urllib.request.urlopen(base + '/api/application/' + aid); assert False
        except urllib.error.HTTPError as error: assert error.code == 403
        for endpoint in ('state', 'jobs'):
            request = urllib.request.Request(base + '/api/' + endpoint, headers={'X-Hireme-Token': 'fixture-capability'})
            with urllib.request.urlopen(request) as response:
                payload = json.loads(response.read())
                assert 'package' not in payload['applications'][0]
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(); requests = []; errors = []; images = []
            screenshot_directory = store.root / 'screenshots'; screenshot_directory.mkdir(mode=0o700, exist_ok=True)
            page.screenshot(path=str(screenshot_directory / 'synthetic-confirmation.jpg'), type='jpeg')
            store.db.execute('UPDATE applications SET screenshot=? WHERE id=?', ('synthetic-confirmation.jpg', aid))
            page.on('request', lambda request: requests.append(request.url) if '/api/application/' in request.url else None)
            page.on('request', lambda request: images.append(request.url) if '/api/screenshot/' in request.url else None)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability')
            summary = page.locator('#jobs').get_by_text('Answers & evidence', exact=True)
            expect(summary).to_be_visible()
            assert not requests
            page.route('**/api/application/*', lambda route: route.fulfill(status=503, json={'error': 'Synthetic temporary outage'}))
            summary.click()
            expect(page.locator('#jobs')).to_contain_text('Synthetic temporary outage')
            page.unroute('**/api/application/*')
            page.locator('#jobs').get_by_role('button', name='Retry evidence').click()
            expect(page.locator('#jobs')).to_contain_text(store.facts()['email']['value'])
            assert len(requests) == 2
            page.route('**/api/screenshot/*', lambda route: route.fulfill(status=200, body='Synthetic invalid image', content_type='image/jpeg'))
            page.locator('#jobs').get_by_role('button', name='View confirmation').click()
            expect(page.locator('#jobs')).to_contain_text('The recorded image could not be displayed')
            page.unroute('**/api/screenshot/*')
            page.locator('#jobs').get_by_role('button', name='View confirmation').click()
            expect(page.locator('#jobs img.evidence')).to_be_visible()
            assert len(images) == 2
            summary.focus(); page.evaluate('refresh()')
            expect(summary.locator('..')).to_have_attribute('open', '')
            expect(summary).to_be_focused()
            expect(page.locator('#jobs')).to_contain_text(store.facts()['email']['value'])
            assert len(requests) == 2
            expect(page.locator('#jobs img.evidence')).to_be_visible()
            assert len(images) == 2
            summary.click(); summary.click()
            expect(page.locator('#jobs')).to_contain_text(store.facts()['email']['value'])
            assert len(requests) == 2 and not errors
            diagnostic = page.locator('#jobs .diagnostic summary')
            diagnostic.click(); page.evaluate('refresh()')
            expect(page.locator('#jobs .diagnostic')).to_have_attribute('open', '')
            expect(diagnostic).to_be_focused()
            store.reconcile(aid, True, 'Synthetic employer verification confirmed submission')
            page.evaluate('refresh()')
            expect(page.locator('#jobs')).to_contain_text('Submitted')
            expect(page.locator('#jobs')).to_contain_text(store.facts()['email']['value'])
            assert len(requests) == 3
            expect(page.locator('#jobs').get_by_role('button', name='View confirmation')).to_be_visible()
            assert len(images) == 2 and not errors
            browser.close()
    finally: process.terminate(); process.join(5)


def test_account_queue_pages_old_holds_and_preserves_verification_drafts(store):
    from playwright.sync_api import sync_playwright, expect
    for index in range(120):
        store.db.execute('INSERT INTO employer_accounts VALUES(?,?,?,?,?)',
            (f'recent-{index}', 'https://jobs.lever.co', f'Recent company {index}', 'confirmed', '2026-10-03T00:00:00+00:00'))
    for index in range(30):
        store.db.execute('INSERT INTO employer_accounts VALUES(?,?,?,?,?)',
            (f'held-{index}', 'https://jobs.lever.co', f'Held company {index}', 'uncertain', '2020-01-01T00:00:00+00:00'))
    store.db.execute('INSERT INTO employer_accounts VALUES(?,?,?,?,?)',
        ('old-special', 'https://jobs.lever.co', 'Café 100%_ Research', 'uncertain', '2019-01-01T00:00:00+00:00'))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = multiprocessing.Process(target=launch, args=(str(store.root), str(Path.cwd()), port)); process.start()
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try: urllib.request.urlopen(base).close(); break
            except OSError: time.sleep(.1)
        try: urllib.request.urlopen(base + '/api/accounts'); assert False
        except urllib.error.HTTPError as error: assert error.code == 403
        with sync_playwright() as p:
            browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 320, 'height': 844}); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#token=fixture-capability')
            page.locator('[data-view=questions]').click()
            expect(page.locator('#account-page')).to_contain_text('1–25 of 31')
            expect(page.locator('#employer-accounts form')).to_have_count(25)
            page.route('**/api/accounts*', lambda route: route.fulfill(status=503, json={'error': 'Synthetic account-history outage'}))
            page.locator('#account-search').fill('Held company')
            expect(page.locator('#account-error')).to_contain_text('Synthetic account-history outage')
            page.unroute('**/api/accounts*')
            page.locator('#account-retry').click()
            expect(page.locator('#account-page')).to_contain_text('1–25 of 30')
            page.locator('#account-search').fill('')
            expect(page.locator('#account-page')).to_contain_text('1–25 of 31')
            proof = page.locator('#employer-accounts textarea').first
            proof.fill('Unsaved synthetic verification evidence')
            expect(page.locator('#account-next')).to_be_disabled()
            expect(page.locator('#account-search')).to_be_disabled()
            proof.blur(); page.evaluate('refresh()')
            expect(proof).to_have_value('Unsaved synthetic verification evidence')
            page.locator('#employer-accounts').get_by_role('button', name='Discard draft').first.click()
            expect(page.locator('#account-next')).to_be_enabled()
            page.locator('#account-next').click()
            expect(page.locator('#account-page')).to_contain_text('26–31 of 31')
            expect(page.locator('#employer-accounts')).to_be_focused()
            expect(page.locator('#employer-accounts')).to_contain_text('Café 100%_ Research')
            page.locator('#account-search').fill('CAFÉ 100%_')
            expect(page.locator('#account-page')).to_contain_text('1–1 of 1')
            expect(page.locator('#employer-accounts form')).to_have_count(1)
            page.locator('#account-search').fill('Recent company 119')
            page.locator('#account-filter').select_option('all')
            expect(page.locator('#employer-accounts')).to_contain_text('Account verified')
            expect(page.locator('#employer-accounts form')).to_have_count(0)
            assert not errors and page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
    finally: process.terminate(); process.join(5)
