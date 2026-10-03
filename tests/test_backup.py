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


def test_backup_and_restore_validate_replaced_documents_in_attempt_history(store,job,package,tmp_path):
    import hashlib
    aid=store.prepare(job,package);store.begin_submit(aid);store.finish(aid,'confirmed')
    old=package['documents'][0]['filename']
    data=b'%PDF-1.4\nSynthetic replacement resume';h=hashlib.sha256(data).hexdigest()
    (store.root/'documents'/(h+'.pdf')).write_bytes(data)
    store.db.execute("UPDATE documents SET hash=?,filename=? WHERE kind='resume'",(h,h+'.pdf'))
    archive=tmp_path/'complete.zip';create_backup(store,archive)
    # A self-consistent manifest can still omit a historical file. The ledger
    # references must independently reject that incomplete restore.
    incomplete=tmp_path/'missing-history.zip'
    with zipfile.ZipFile(archive) as source,zipfile.ZipFile(incomplete,'w') as target:
        manifest=json.loads(source.read('manifest.json'));manifest['files'].pop('documents/'+old)
        for name in source.namelist():
            if name=='documents/'+old:continue
            target.writestr(name,json.dumps(manifest) if name=='manifest.json' else source.read(name))
    with pytest.raises(ValueError,match='missing or changed'):restore_backup(incomplete,tmp_path/'incomplete-restore')
    assert not (tmp_path/'incomplete-restore').exists()
    (store.root/'documents'/old).unlink()
    with pytest.raises(ValueError,match='missing or changed'):create_backup(store,tmp_path/'missing-history-backup.zip')
    assert not (tmp_path/'missing-history-backup.zip').exists()


def test_backup_retains_withdrawn_transcript_evidence_and_checks_missing_screenshots(store,job,package,tmp_path):
    from hireme.document_controls import withdraw_transcript
    resume=package['documents'][0]
    store.db.execute('INSERT INTO documents VALUES(?,?,?)',('transcript',resume['hash'],resume['filename']))
    aid=store.prepare(job,{**package,'documents':[*package['documents'],{**resume,'kind':'transcript'}]})
    store.begin_submit(aid)
    directory=store.root/'screenshots';directory.mkdir()
    name=aid+'-after.jpg';(directory/name).write_bytes(b'Synthetic screenshot bytes')
    store.finish(aid,'unknown',screenshot=name)
    withdraw_transcript(store)
    archive=tmp_path/'withdrawn-history.zip';create_backup(store,archive)
    restored_root=tmp_path/'withdrawn-restored';restore_backup(archive,restored_root)
    restored=Store(restored_root)
    try:
        assert not restored.db.execute("SELECT 1 FROM documents WHERE kind='transcript'").fetchone()
        assert (restored.root/'documents'/resume['filename']).is_file()
        assert (restored.root/'screenshots'/name).is_file()
        assert restored.db.execute('SELECT state FROM applications').fetchone()[0]=='unknown'
    finally:restored.close()
    (directory/name).unlink()
    with pytest.raises(ValueError,match='screenshot is missing'):create_backup(store,tmp_path/'missing-shot.zip')
    assert not (tmp_path/'missing-shot.zip').exists()


def test_backup_rejects_referenced_document_types_the_archive_cannot_preserve(store,tmp_path):
    import hashlib
    data=b'Synthetic unsupported upload';h=hashlib.sha256(data).hexdigest()
    (store.root/'documents'/(h+'.docx')).write_bytes(data)
    store.db.execute("UPDATE documents SET hash=?,filename=? WHERE kind='resume'",(h,h+'.docx'))
    with pytest.raises(ValueError,match='Invalid document reference'):create_backup(store,tmp_path/'unsupported-document.zip')
    assert not (tmp_path/'unsupported-document.zip').exists()


def test_backup_preserves_unreadable_legacy_package_text_for_recovery(store,job,package,tmp_path):
    aid=store.prepare(job,package);store.begin_submit(aid);store.finish(aid,'confirmed')
    raw='Synthetic unreadable legacy evidence text'
    store.db.execute('UPDATE applications SET package=? WHERE id=?',(raw,aid))
    archive=tmp_path/'legacy-recovery.zip';create_backup(store,archive)
    restored_root=tmp_path/'legacy-restored';restore_backup(archive,restored_root)
    restored=Store(restored_root)
    try:assert restored.db.execute('SELECT package FROM applications WHERE id=?',(aid,)).fetchone()[0]==raw
    finally:restored.close()
