import pytest

from hireme.company_controls import skip_company
from hireme.ledger import search_jobs
from hireme.util import Blocked, digest


def test_skip_company_respects_aliases_and_clears_only_unattempted_work(store, job, package):
    store.update_settings({'company_aliases': {'Acme': 'Acme Technologies'}})
    second = {**job, 'id': digest('second-company-role'), 'url': job['url'] + '-second', 'company': 'ACME Technologies'}
    store.upsert_job(second)
    qid = store.ask(second['id'], second['host'], 'Future application question', [])
    aid = store.prepare(job, package)
    generation = store.control_generation()
    skip_company(store, job['id'])
    assert store.settings()['skip_companies'] == ['Acme']
    assert store.control_generation() == generation and store.settings()['live_enabled']
    assert not store.db.execute('SELECT * FROM applications WHERE id=?', (aid,)).fetchone()
    assert store.db.execute('SELECT resolved FROM questions WHERE id=?', (qid,)).fetchone()[0] == 1
    jobs = search_jobs(store)['jobs']
    assert all(row['company_skipped'] and row['reason'] == 'company_blocked' for row in jobs)
    with pytest.raises(Blocked, match='company_blocked'): store.prepare(job, package)
    skip_company(store, second['id'])
    assert store.settings()['skip_companies'] == ['Acme']


@pytest.mark.parametrize('state', ['submitting', 'confirmed', 'unknown', 'awaiting_verification'])
def test_skip_company_never_rewrites_attempt_or_its_pending_questions(store, job, package, state):
    aid = store.prepare(job, package); store.begin_submit(aid)
    if state != 'submitting': store.finish(aid, state)
    qid = store.ask(job['id'], job['host'], 'Past attempt verification', [])
    application = dict(store.db.execute('SELECT * FROM applications WHERE id=?', (aid,)).fetchone())
    original = dict(store.db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone())
    skip_company(store, job['id'])
    assert dict(store.db.execute('SELECT * FROM applications WHERE id=?', (aid,)).fetchone()) == application
    assert dict(store.db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone()) == original
    assert store.db.execute('SELECT resolved FROM questions WHERE id=?', (qid,)).fetchone()[0] == 0


def test_unknown_opportunity_cannot_change_company_boundaries(store):
    original = store.settings()
    with pytest.raises(ValueError): skip_company(store, 'unknown')
    assert store.settings() == original
