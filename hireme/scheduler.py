from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from .util import private_dir

LABEL='com.pleasehireme.worker.v3'


def install(store,repo):
    if store.missing_setup() or not store.settings()['onboarding_complete']:
        raise ValueError('Complete onboarding before installing automatic runs')
    hours=store.settings()['schedule_hours']
    if sys.platform=='darwin':
        directory=Path.home()/'Library/LaunchAgents';directory.mkdir(parents=True,exist_ok=True)
        path=directory/(LABEL+'.plist')
        if path.is_symlink():raise ValueError('Unsafe LaunchAgent path')
        logs=private_dir(store.root/'logs')
        payload={'Label':LABEL,'ProgramArguments':[sys.executable,'-m','hireme','--data-dir',str(store.root),'run'],
          'WorkingDirectory':str(repo),'StartInterval':hours*3600,'RunAtLoad':False,
          'StandardOutPath':str(logs/'worker.out.log'),'StandardErrorPath':str(logs/'worker.err.log'),
          'EnvironmentVariables':{'PATH':os.environ.get('PATH','/usr/local/bin:/usr/bin:/bin'),
              **{k:os.environ[k] for k in ('ANTHROPIC_API_KEY','CLAUDE_CODE_OAUTH_TOKEN','CLAUDE_CONFIG_DIR','XDG_CONFIG_HOME') if os.environ.get(k)}}}
        # Connection secrets stay in a private file, never argv or logs.
        with tempfile.NamedTemporaryFile(dir=directory,prefix='.'+LABEL,delete=False) as f:
            temporary=Path(f.name)
            try:
                f.write(plistlib.dumps(payload));f.flush();os.fsync(f.fileno())
                os.replace(temporary,path)
            finally:temporary.unlink(missing_ok=True)
        subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{LABEL}'],capture_output=True)
        r=subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(path)],capture_output=True)
        if r.returncode:raise ValueError('launchd rejected worker; run hireme daemon in a terminal')
        return str(path)
    if 24%hours:raise ValueError('Cron requires a schedule dividing 24 hours')
    r=subprocess.run(['crontab','-l'],capture_output=True,text=True)
    lines=[l for l in r.stdout.splitlines() if not l.endswith('# '+LABEL)]
    command='cd '+shlex.quote(str(repo))+' && '+shlex.join([sys.executable,'-m','hireme','--data-dir',str(store.root),'run'])
    command=command.replace('%',r'\%')
    lines.append(f'0 */{hours} * * * {command} # {LABEL}')
    subprocess.run(['crontab','-'],input='\n'.join(lines)+'\n',text=True,check=True)
    return 'cron'


def uninstall():
    if sys.platform=='darwin':
        subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{LABEL}'],capture_output=True)
        path=Path.home()/'Library/LaunchAgents'/(LABEL+'.plist')
        if path.exists() and not path.is_symlink():
            payload=plistlib.loads(path.read_bytes())
            if payload.get('Label')==LABEL:path.unlink()
    else:
        r=subprocess.run(['crontab','-l'],capture_output=True,text=True)
        lines=[l for l in r.stdout.splitlines() if not l.endswith('# '+LABEL)]
        subprocess.run(['crontab','-'],input='\n'.join(lines)+'\n',text=True,check=True)


def status():
    if sys.platform=='darwin':
        p=Path.home()/'Library/LaunchAgents'/(LABEL+'.plist')
        return {'installed':p.is_file(),'path':str(p)}
    r=subprocess.run(['crontab','-l'],capture_output=True,text=True)
    return {'installed':any(l.endswith('# '+LABEL) for l in r.stdout.splitlines())}
