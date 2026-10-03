from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .store import Store,worker_lock
from .util import Blocked

REPO=Path(__file__).resolve().parent.parent
DEFAULT_ROOT=Path.home()/'.local/share/please-hire-me'


def main(argv=None):
    parser=argparse.ArgumentParser(description='Automatic job applications with verified facts')
    parser.add_argument('--data-dir',type=Path,default=DEFAULT_ROOT)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('open-dashboard');p.add_argument('--port',type=int,default=8766)
    p=sub.add_parser('dashboard');p.add_argument('--port',type=int,default=8766)
    p=sub.add_parser('import-material');p.add_argument('path',type=Path);p.add_argument('--kind',choices=['writing_sample','cover_letter','context'],required=True)
    p=sub.add_parser('import-resume');p.add_argument('path',type=Path);p.add_argument('--transcript',action='store_true')
    p=sub.add_parser('gmail');p.add_argument('action',choices=['import-client','connect','status','disconnect']);p.add_argument('path',type=Path,nargs='?')
    p=sub.add_parser('backup');p.add_argument('path',type=Path)
    p=sub.add_parser('restore');p.add_argument('path',type=Path)
    p=sub.add_parser('account-vault');p.add_argument('action',choices=['export','import']);p.add_argument('path',type=Path)
    p=sub.add_parser('pi');p.add_argument('action',choices=['configure','preflight','units','install']);p.add_argument('--directory',type=Path)
    p=sub.add_parser('reports');p.add_argument('action',choices=['status','flush'])
    sub.add_parser('resume-candidates')
    p=sub.add_parser('run');p.add_argument('--no-discovery',action='store_true');p.add_argument('--prepare-only',action='store_true');p.add_argument('--limit',type=int);p.add_argument('--max-attempts',type=int);p.add_argument('--job-id',action='append',default=[])
    sub.add_parser('daemon')
    p=sub.add_parser('discover');p.add_argument('--source',choices=['all','delta','portal','list'],default='all');p.add_argument('--ats');p.add_argument('--limit',type=int)
    p=sub.add_parser('schedule');p.add_argument('action',choices=['install','uninstall','status'],default='status',nargs='?')
    p=sub.add_parser('duplicate');p.add_argument('company');p.add_argument('req',nargs='?')
    p=sub.add_parser('ashby-fields');p.add_argument('slug');p.add_argument('req')
    p=sub.add_parser('import-tracker');p.add_argument('path',type=Path)
    sub.add_parser('status')
    sub.add_parser('pause');sub.add_parser('resume')
    p=sub.add_parser('login');p.add_argument('url')
    p=sub.add_parser('import-legacy');p.add_argument('path',type=Path,default=REPO,nargs='?')
    args=parser.parse_args(argv)
    os.umask(0o077)
    if args.command=='restore':
        from .backup import restore_backup
        try:print(json.dumps(restore_backup(args.path,args.data_dir.expanduser().absolute())));return 0
        except ValueError as e:print(str(e),file=sys.stderr);return 2
    store=Store(args.data_dir.expanduser().absolute())
    try:
        if args.command=='dashboard':
            from .server import serve
            store.close();serve(args.data_dir.expanduser().absolute(),REPO,args.port);return
        if args.command=='import-resume':
            from .onboarding import import_resume
            r=import_resume(store,args.path.expanduser(),'transcript' if args.transcript else 'resume')
            print(json.dumps({'imported':r['hash'],'candidate_fields':sorted(r['candidates']),'next':'Confirm facts and finish setup in the dashboard'}))
        elif args.command=='resume-candidates':
            from .onboarding import model_candidates
            from .provider import ManagedProvider
            print(json.dumps(model_candidates(store,ManagedProvider(store,store.settings()['model_timeout_seconds']))))
        elif args.command=='backup':
            from .backup import create_backup
            print(json.dumps(create_backup(store,args.path)))
        elif args.command=='account-vault':
            import getpass
            from .account_transfer import export_accounts,import_accounts
            if not sys.stdin.isatty():raise ValueError('Use an interactive terminal for the transfer passphrase')
            phrase=getpass.getpass('Credential-transfer passphrase: ')
            if args.action=='export':
                if phrase!=getpass.getpass('Confirm passphrase: '):raise ValueError('Passphrases do not match')
                result=export_accounts(store,args.path.expanduser(),phrase)
            else:result=import_accounts(store,args.path.expanduser(),phrase)
            print(json.dumps(result))
        elif args.command=='open-dashboard':
            import webbrowser
            from .server import dashboard_url
            if not webbrowser.open(dashboard_url(store.root,args.port)):raise ValueError('Open the dashboard from a terminal in the Pi desktop session')
        elif args.command=='pi':
            from . import pi
            if args.action=='configure':result=pi.configure(store)
            elif args.action=='preflight':result=pi.preflight(store)
            else:result=pi.install(store,REPO,args.directory,enable=args.action=='install')
            print(json.dumps(result,indent=2))
        elif args.command=='reports':
            from .reports import report_status,flush_reports
            print(json.dumps(report_status(store) if args.action=='status' else flush_reports(store)))
        elif args.command=='gmail':
            from . import gmail
            if args.action=='import-client':
                if not args.path:raise ValueError('Provide the Google Desktop OAuth client JSON path')
                gmail.import_client(store,args.path);print('Google OAuth client stored privately')
            elif args.action=='connect':print(json.dumps(gmail.connect(store)))
            elif args.action=='status':print(json.dumps(gmail.status(store)))
            else:gmail.disconnect(store);print('Local Gmail credentials removed; revoke access in your Google account if desired')
        elif args.command=='import-material':
            from .materials import import_material
            if args.path.is_symlink() or not args.path.is_file():raise ValueError('Choose a regular source file')
            if args.path.stat().st_size>20*1024*1024:raise ValueError('Source exceeds 20 MiB')
            print(json.dumps(import_material(store,args.path.read_bytes(),args.path.name,args.kind)))
        elif args.command=='run':
            from .worker import cycle
            if args.limit is not None and not 1<=args.limit<=50:raise ValueError('Limit must be 1–50')
            if args.max_attempts is not None and not 1<=args.max_attempts<=50:raise ValueError('Attempts must be 1–50')
            if args.job_id and any(not store.db.execute('SELECT 1 FROM jobs WHERE id=?',(jid,)).fetchone() for jid in args.job_id):raise ValueError('Unknown job ID')
            print(json.dumps(cycle(store,REPO,not args.no_discovery,not args.prepare_only,args.limit,max_attempts=args.max_attempts,job_ids=set(args.job_id))))
        elif args.command=='daemon':
            from .worker import daemon
            daemon(store,REPO)
        elif args.command=='discover':
            from .discovery import sweep_boards,sweep_lists,sweep_portals
            with worker_lock(store.root):
                if args.source in ('all','list'):sweep_lists(store)
                if args.source in ('all','portal'):sweep_portals(store)
                if args.source in ('all','delta'):sweep_boards(store,REPO,args.ats.split(',') if args.ats else None,args.limit)
            print(json.dumps({'jobs':store.db.execute('SELECT count(*) FROM jobs').fetchone()[0]}))
        elif args.command=='schedule':
            from . import scheduler
            if args.action=='install':print(scheduler.install(store,REPO))
            elif args.action=='uninstall':scheduler.uninstall();print('Worker schedule removed')
            else:print(json.dumps(scheduler.status()))
        elif args.command=='duplicate':
            ck=store.company(args.company)
            rows=[dict(r) for r in store.db.execute("SELECT id,state,created,attempted FROM applications WHERE company_key=?",(ck,))]
            blocked=ck in {store.company(x) for x in store.settings()['skip_companies']+store.settings()['interview_companies']}
            print(json.dumps({'company':ck,'blocked':blocked,'applications':rows}))
            return 3 if blocked else 1 if rows else 0
        elif args.command=='ashby-fields':
            import re
            from .net import Network
            if not re.fullmatch(r'[A-Za-z0-9._-]{1,100}',args.slug) or not re.fullmatch(r'[A-Za-z0-9-]{1,100}',args.req):raise ValueError('Invalid slug or req')
            query='query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) { jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) { applicationForm { sections { title fieldEntries { field isRequired } } } } }'
            result=Network().json('https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting',{'operationName':'ApiJobPosting','variables':{'organizationHostedJobsPageName':args.slug,'jobPostingId':args.req},'query':query})
            print(json.dumps(result))
        elif args.command=='import-tracker':
            import re
            if args.path.is_symlink() or not args.path.is_file():raise ValueError('Tracker must be a readable regular file')
            companies=[m.group(1).strip() for m in re.finditer(r'\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]',args.path.read_text())]
            if not companies:raise ValueError('No wikilinked companies found; nothing was changed')
            store.update_settings({'interview_companies':sorted(set(store.settings()['interview_companies'])|set(companies))})
            print(json.dumps({'blocked_companies':companies}))
        elif args.command=='status':
            print(json.dumps({'missing_setup':store.missing_setup(),'settings':store.settings(),'runs':store.snapshot()['runs']},indent=2))
        elif args.command in ('pause','resume'):store.update_settings({'live_enabled':args.command=='resume'});print(args.command)
        elif args.command=='login':
            from .discovery import ATS_HOSTS,PORTAL_HOSTS
            from .util import canonical_url,public_host
            from urllib.parse import urlsplit
            url=canonical_url(args.url);host=urlsplit(url).hostname
            if host not in ATS_HOSTS|PORTAL_HOSTS or not public_host(host):raise ValueError('Unapproved portal')
            from playwright.sync_api import sync_playwright
            with worker_lock(store.root,'browser'),sync_playwright() as p:
                from .util import private_dir
                channel=store.settings()['browser_channel']
                browser_options={'channel':'chrome'} if channel=='chrome' else {}
                if channel=='system-chromium':
                    import shutil
                    executable=shutil.which('chromium') or shutil.which('chromium-browser')
                    if not executable:raise ValueError('Install system Chromium first')
                    browser_options={'executable_path':executable}
                ctx=p.chromium.launch_persistent_context(str(private_dir(store.root/'browser')),headless=False,
                     **browser_options,accept_downloads=False)
                page=ctx.pages[0] if ctx.pages else ctx.new_page();page.goto(url)
                print('Sign in yourself in the dedicated browser. Press Enter here when finished.')
                input();ctx.close()
            store.update_settings({'signed_in_portals':sorted(set(store.settings()['signed_in_portals'])|{host})})
        elif args.command=='import-legacy':
            # Legacy personal profile is a proposal. Historical application records block resubmission.
            from .migration import import_legacy
            print(json.dumps(import_legacy(store,args.path)))
    except (Blocked,ValueError) as e:
        print(str(e),file=sys.stderr);return 2
    finally:
        try:store.close()
        except Exception:pass
    return 0
