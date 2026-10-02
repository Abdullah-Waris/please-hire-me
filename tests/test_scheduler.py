from types import SimpleNamespace
from pathlib import Path
import os
import plistlib
from hireme.scheduler import install,LABEL


def test_mac_schedule_preserves_claude_connection_in_private_plist_not_argv(store,tmp_path,monkeypatch):
    monkeypatch.setattr('hireme.scheduler.sys.platform','darwin')
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY','synthetic-key')
    monkeypatch.setenv('UNRELATED_SECRET','must-not-forward')
    calls=[]
    def run(args,**kwargs):calls.append(args);return SimpleNamespace(returncode=0)
    monkeypatch.setattr('hireme.scheduler.subprocess.run',run)
    path=Path(install(store,tmp_path/'repo with spaces'))
    data=plistlib.loads(path.read_bytes())
    assert data['Label']==LABEL
    assert data['EnvironmentVariables']['ANTHROPIC_API_KEY']=='synthetic-key'
    assert 'UNRELATED_SECRET' not in data['EnvironmentVariables']
    assert 'synthetic-key' not in ' '.join(data['ProgramArguments'])
    assert 'synthetic-key' not in ' '.join(' '.join(c) for c in calls)
    assert path.stat().st_mode & 0o777==0o600
