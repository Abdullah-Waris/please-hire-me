import json
import os
import pytest

from hireme.accounts import AccountVault, account_key
from hireme.backup import create_backup, restore_backup
from hireme.store import Store
from hireme.util import Blocked

ORIGIN = 'https://careers.example.com'


def test_credentials_are_private_scoped_and_not_logged(store):
    vault = AccountVault(store)
    value = vault.credentials(ORIGIN, 'Acme', create=True)
    assert value == vault.credentials(ORIGIN, 'Acme')
    other = vault.credentials(ORIGIN, 'Other employer', create=True)
    assert value['password'] != other['password']
    path = vault.directory / (account_key(ORIGIN, 'Acme') + '.json')
    assert os.stat(path).st_mode & 0o777 == 0o600
    key = vault.begin_creation(ORIGIN, 'Acme')
    vault.finish_creation(key, confirmed=True)
    assert store.db.execute('SELECT state FROM employer_accounts WHERE id=?', (key,)).fetchone()[0] == 'confirmed'
    assert value['password'] not in json.dumps([dict(r) for r in store.db.execute('SELECT * FROM events')])
    assert value['password'].encode() not in store.path.read_bytes()


def test_crash_and_uncertain_creation_cannot_retry(store):
    vault = AccountVault(store)
    vault.credentials(ORIGIN, 'Acme', create=True)
    key = vault.begin_creation(ORIGIN, 'Acme')
    store.recover()
    assert store.db.execute('SELECT state FROM employer_accounts WHERE id=?', (key,)).fetchone()[0] == 'uncertain'
    with pytest.raises(Blocked, match='account_creation_held'):
        vault.begin_creation(ORIGIN, 'Acme')
    with pytest.raises(Blocked, match='account_creation_held'):
        vault.finish_creation(key, confirmed=True)


def test_restore_preserves_intent_without_credentials(store, tmp_path):
    vault = AccountVault(store)
    secret = vault.credentials(ORIGIN, 'Acme', create=True)['password']
    vault.begin_creation(ORIGIN, 'Acme')
    archive = tmp_path / 'backup.zip'
    create_backup(store, archive)
    destination = tmp_path / 'restored'
    restore_backup(archive, destination)
    restored = Store(destination)
    try:
        assert secret.encode() not in restored.path.read_bytes()
        with pytest.raises(Blocked, match='account_credentials_unavailable'):
            AccountVault(restored).credentials(ORIGIN, 'Acme', create=True)
        assert restored.db.execute('SELECT state FROM employer_accounts').fetchone()[0] == 'uncertain'
    finally:
        restored.close()


def test_paused_creation_never_records_intent(store):
    vault = AccountVault(store)
    vault.credentials(ORIGIN, 'Acme', create=True)
    store.run_generation = store.control_generation()
    store.update_settings({'live_enabled': False})
    with pytest.raises(Blocked, match='paused'):
        vault.begin_creation(ORIGIN, 'Acme')
    assert not store.db.execute('SELECT 1 FROM employer_accounts').fetchone()


@pytest.mark.parametrize('origin', ['http://careers.example.com', 'https://u:p@careers.example.com',
                                  'https://careers.example.com/create', 'https://careers.example.com?redirect=x'])
def test_rejects_ambiguous_origins(origin):
    with pytest.raises(ValueError):
        account_key(origin, 'Acme')


def test_changed_identity_and_symlinks_are_held(store, tmp_path):
    vault = AccountVault(store)
    vault.credentials(ORIGIN, 'Acme', create=True)
    store.put_facts({'email': 'different@candidate.invalid'})
    with pytest.raises(Blocked, match='account_credentials_unavailable'):
        vault.credentials(ORIGIN, 'Acme')
    path = vault.directory / (account_key(ORIGIN, 'Other') + '.json')
    path.symlink_to(tmp_path / 'outside')
    with pytest.raises(Blocked, match='account_credentials_unavailable'):
        vault.credentials(ORIGIN, 'Other', create=True)
