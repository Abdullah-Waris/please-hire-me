import json
import zipfile
from pathlib import Path
import pytest
from hireme.backup import create_backup,restore_backup
from hireme.store import Store
from hireme.materials import import_material,review_material


def test_backup_restores_identity_documents_and_history_paused_without_tokens(store,job,package,tmp_path):
    aid=store.prepare(job,package);store.begin_submit(aid);store.finish(aid,'confirmed','Application received')
    source=import_material(store,b'I built Python services for operational workflows.','sample.txt','context')
    review_material(store,source['id'],source['text'],'personal',True)
    from hireme.util import atomic_json
    atomic_json(store.root/'integrations/gmail-token.json',{'token':'synthetic-secret'})
    archive=tmp_path/'backup.zip';result=create_backup(store,archive)
    assert not result['credentials_included'] and store.settings()['live_enabled']
    with zipfile.ZipFile(archive) as z:assert not any('integrations' in name for name in z.namelist())
    root=tmp_path/'restored';restore_backup(archive,root)
    restored=Store(root)
    assert restored.facts()==store.facts() and not restored.settings()['live_enabled']
    assert restored.db.execute('SELECT state FROM applications').fetchone()[0]=='confirmed'
    assert restored.db.execute('SELECT text FROM materials').fetchone()[0]==source['text']
    doc=restored.db.execute('SELECT filename FROM documents').fetchone()[0]
    assert (root/'documents'/doc).is_file()
    assert not (root/'integrations/gmail-token.json').exists()
    restored.close()
    with pytest.raises(ValueError):restore_backup(archive,root)
    with pytest.raises(ValueError):create_backup(store,archive)


def test_backup_tampering_or_path_traversal_is_rejected(store,tmp_path):
    archive=tmp_path/'backup.zip';create_backup(store,archive)
    bad=tmp_path/'tampered.zip'
    with zipfile.ZipFile(archive) as src,zipfile.ZipFile(bad,'w') as dst:
        for name in src.namelist():dst.writestr(name,b'changed' if name=='ledger.sqlite3' else src.read(name))
    with pytest.raises(ValueError):restore_backup(bad,tmp_path/'bad-root')
    assert not (tmp_path/'bad-root').exists()
    traversal=tmp_path/'traversal.zip'
    with zipfile.ZipFile(traversal,'w') as z:
        z.writestr('../outside','bad');z.writestr('manifest.json',json.dumps({'version':1,'files':{'../outside':{'bytes':3,'sha256':'bad'}}}))
    with pytest.raises(ValueError):restore_backup(traversal,tmp_path/'traversal-root')
    assert not (tmp_path/'outside').exists()


def test_backup_refuses_missing_referenced_document(store,tmp_path):
    name=store.db.execute('SELECT filename FROM documents').fetchone()[0]
    (store.root/'documents'/name).unlink()
    with pytest.raises(ValueError,match='missing or changed'):create_backup(store,tmp_path/'incomplete.zip')
    assert not (tmp_path/'incomplete.zip').exists()
