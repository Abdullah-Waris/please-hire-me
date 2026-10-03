import json
import os

import pytest

from hireme.account_transfer import export_accounts, import_accounts
from hireme.accounts import AccountVault
from hireme.backup import create_backup, restore_backup
from hireme.cli import main
from hireme.store import Store, worker_lock
from hireme.util import Blocked

ORIGIN='https://careers.example.com'
PHRASE='synthetic transfer passphrase only'


def account(store, company='Acme', confirmed=True):
    vault=AccountVault(store)
    credential=vault.credentials(ORIGIN,company,create=True)
    key=vault.begin_creation(ORIGIN,company)
    vault.finish_creation(key,confirmed=confirmed)
    store.update_settings({'live_enabled':False})
    return key,credential


def test_encrypted_transfer_recovers_restored_credentials_without_resuming(store,tmp_path):
    key,credential=account(store)
    archive=tmp_path/'accounts.encrypted';export_accounts(store,archive,PHRASE)
    assert os.stat(archive).st_mode&0o777==0o600
    assert credential['password'].encode() not in archive.read_bytes()
    assert credential['email'].encode() not in archive.read_bytes()
    history=tmp_path/'history.zip';create_backup(store,history)
    root=tmp_path/'restored';restore_backup(history,root)
    restored=Store(root)
    try:
        result=import_accounts(restored,archive,PHRASE)
        assert result=={'accounts':1,'states_preserved':True,'paused':True}
        assert AccountVault(restored).credentials(ORIGIN,'Acme')==credential
        assert restored.db.execute('SELECT state FROM employer_accounts WHERE id=?',(key,)).fetchone()[0]=='confirmed'
        assert not restored.settings()['live_enabled']
        assert import_accounts(restored,archive,PHRASE)['accounts']==1
        assert credential['password'] not in json.dumps(restored.snapshot())
        assert credential['password'] not in str([dict(r) for r in restored.db.execute('SELECT * FROM events')])
    finally:restored.close()


def test_wrong_passphrase_tampering_and_overwrite_leave_credentials_unchanged(store,tmp_path):
    _,credential=account(store)
    archive=tmp_path/'accounts.encrypted';export_accounts(store,archive,PHRASE)
    with pytest.raises(ValueError,match='new credential-transfer'):export_accounts(store,archive,PHRASE)
    with pytest.raises(ValueError,match='incorrect passphrase'):import_accounts(store,archive,'different synthetic passphrase')
    envelope=json.loads(archive.read_text());envelope['token']=envelope['token'][:-4]+'AAAA';archive.write_text(json.dumps(envelope))
    with pytest.raises(ValueError,match='incorrect passphrase'):import_accounts(store,archive,PHRASE)
    assert AccountVault(store).credentials(ORIGIN,'Acme')==credential


def test_uncertain_accounts_remain_held_after_transfer(store,tmp_path):
    key,_=account(store,confirmed=False)
    archive=tmp_path/'accounts.encrypted';export_accounts(store,archive,PHRASE)
    import_accounts(store,archive,PHRASE)
    assert store.db.execute('SELECT state FROM employer_accounts WHERE id=?',(key,)).fetchone()[0]=='uncertain'


def test_different_identity_or_missing_history_is_rejected(store,tmp_path):
    account(store)
    archive=tmp_path/'accounts.encrypted';export_accounts(store,archive,PHRASE)
    destination=Store(tmp_path/'different')
    try:
        destination.put_facts({'email':'another@candidate.invalid'})
        with pytest.raises(ValueError,match='different applicant'):import_accounts(destination,archive,PHRASE)
        destination.put_facts({'email':'test@candidate.invalid'})
        with pytest.raises(ValueError,match='matching account history'):import_accounts(destination,archive,PHRASE)
        assert not list((destination.root/'integrations/accounts').glob('*.json'))
    finally:destination.close()


def test_conflicting_credentials_reject_entire_import(store,tmp_path):
    account(store,'Acme');second,credential=account(store,'Other')
    archive=tmp_path/'accounts.encrypted';export_accounts(store,archive,PHRASE)
    vault=AccountVault(store)
    first=store.db.execute("SELECT id FROM employer_accounts WHERE company='Acme'").fetchone()[0]
    (vault.directory/(first+'.json')).unlink()
    changed={'email':credential['email'],'password':'different-password-12345'}
    (vault.directory/(second+'.json')).write_text(json.dumps(changed))
    with pytest.raises(ValueError,match='credentials differ'):import_accounts(store,archive,PHRASE)
    assert not (vault.directory/(first+'.json')).exists()
    assert vault.credentials(ORIGIN,'Other')==changed


def test_pause_worker_lock_and_symlink_boundaries(store,tmp_path):
    account(store)
    archive=tmp_path/'accounts.encrypted'
    with worker_lock(store.root):
        with pytest.raises(Blocked,match='worker_busy'):export_accounts(store,archive,PHRASE)
    store.update_settings({'live_enabled':True})
    with pytest.raises(ValueError,match='Pause'):export_accounts(store,archive,PHRASE)
    store.update_settings({'live_enabled':False});export_accounts(store,archive,PHRASE)
    link=tmp_path/'link';link.symlink_to(archive)
    with pytest.raises(ValueError):export_accounts(store,link,PHRASE)
    with pytest.raises(ValueError):import_accounts(store,link,PHRASE)


def test_cli_uses_interactive_hidden_prompt_and_never_outputs_password(store,tmp_path,monkeypatch,capsys):
    _,credential=account(store)
    monkeypatch.setattr('sys.stdin.isatty',lambda:True)
    monkeypatch.setattr('getpass.getpass',lambda prompt:PHRASE)
    archive=tmp_path/'accounts.encrypted'
    assert main(['--data-dir',str(store.root),'account-vault','export',str(archive)])==0
    assert main(['--data-dir',str(store.root),'account-vault','import',str(archive)])==0
    output=capsys.readouterr()
    assert credential['password'] not in output.out+output.err and PHRASE not in output.out+output.err
    monkeypatch.setattr('sys.stdin.isatty',lambda:False)
    assert main(['--data-dir',str(store.root),'account-vault','export',str(tmp_path/'never')])==2
    assert not (tmp_path/'never').exists()


def test_interrupted_import_can_resume_without_changing_account_states(store,tmp_path,monkeypatch):
    account(store,'Acme');account(store,'Other',confirmed=False)
    archive=tmp_path/'accounts.encrypted';export_accounts(store,archive,PHRASE)
    vault=AccountVault(store)
    for path in vault.directory.glob('*.json'):path.unlink()
    from hireme import account_transfer
    original=account_transfer.atomic_json
    calls=[]
    def interrupt(path,value):
        calls.append(path)
        if len(calls)==2:raise OSError('Synthetic interrupted import')
        original(path,value)
    monkeypatch.setattr(account_transfer,'atomic_json',interrupt)
    with pytest.raises(OSError):import_accounts(store,archive,PHRASE)
    assert len(list(vault.directory.glob('*.json')))==1
    monkeypatch.setattr(account_transfer,'atomic_json',original)
    assert import_accounts(store,archive,PHRASE)['accounts']==2
    assert len(list(vault.directory.glob('*.json')))==2
    assert [r[0] for r in store.db.execute('SELECT state FROM employer_accounts ORDER BY company')]==['confirmed','uncertain']
