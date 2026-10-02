from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlsplit

from .config import FACTS,REQUIRED
from .store import Store

MAX_BODY=21*1024*1024


def serve(root,repo,port=8766,token=None):
    token=token or secrets.token_urlsafe(32); state={'running':False,'lock':threading.Lock()}
    assets=Path(__file__).parent/'static'
    def start_cycle():
        with state['lock']:
            if state['running']:raise ValueError('A dashboard-triggered run is already active')
            state['running']=True
        def run():
            from .worker import cycle
            worker=Store(root)
            try:cycle(worker,repo)
            except Exception as e:worker.event('dashboard_run_failed','worker',{'type':type(e).__name__,'message':str(e)[:500]})
            finally:
                worker.close()
                with state['lock']:state['running']=False
        threading.Thread(target=run,daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass  # URL capability and personal input must not enter access logs.
        def _valid_host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{port}',f'localhost:{port}')
        def _auth(self):
            origin=self.headers.get('Origin')
            return self._valid_host() and secrets.compare_digest(self.headers.get('X-Hireme-Token',''),token) and origin in (None,f'http://127.0.0.1:{port}',f'http://localhost:{port}')
        def send(self,code,data,ctype='application/json'):
            body=json.dumps(data).encode() if ctype=='application/json' else data
            self.send_response(code)
            self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
            self.end_headers();self.wfile.write(body)
        def do_GET(self):
            path=urlsplit(self.path).path
            if not self._valid_host():return self.send(403,{'error':'Invalid host'})
            if path in ('/','/app.js','/style.css'):
                name={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[path]
                return self.send(200,(assets/name).read_bytes(),{'/':'text/html; charset=utf-8','/app.js':'text/javascript','/style.css':'text/css'}[path])
            if not self._auth():return self.send(403,{'error':'Open the dashboard URL printed by hireme dashboard'})
            store=Store(root)
            try:
                if path=='/api/state':return self.send(200,{**store.snapshot(),'fact_labels':FACTS,'required':sorted(REQUIRED),'worker_running':state['running']})
                if path.startswith('/api/screenshot/'):
                    name=path.rsplit('/',1)[-1]
                    if '/' in name or '..' in name:return self.send(400,{'error':'Invalid screenshot'})
                    p=root/'screenshots'/name
                    if p.is_symlink() or not p.is_file():return self.send(404,{'error':'Not found'})
                    return self.send(200,p.read_bytes(),'image/jpeg')
                return self.send(404,{'error':'Not found'})
            finally:store.close()
        def do_POST(self):
            if not self._auth():return self.send(403,{'error':'Unauthorized local request'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=MAX_BODY:return self.send(413,{'error':'Request too large'})
                raw=self.rfile.read(size);path=urlsplit(self.path).path
                store=Store(root)
                try:
                    if path in ('/api/resume','/api/transcript'):
                        import tempfile
                        from .onboarding import import_resume
                        with tempfile.NamedTemporaryFile(suffix='.pdf',dir=root) as f:
                            f.write(raw);f.flush();result=import_resume(store,Path(f.name),'transcript' if path=='/api/transcript' else 'resume')
                        return self.send(200,{'hash':result['hash'],'candidates':result['candidates']})
                    data=json.loads(raw)
                    if path=='/api/facts':store.put_facts(data['facts']);result={'saved':True}
                    elif path=='/api/answer':store.answer_question(data['id'],data['value'],data.get('fact_key'));result={'saved':True}
                    elif path=='/api/template':result={'id':store.put_template(data['category'],data['body'])}
                    elif path=='/api/settings':result=store.update_settings(data)
                    elif path=='/api/complete-setup':
                        if store.missing_setup():raise ValueError('Missing: '+', '.join(store.missing_setup()))
                        store.update_settings({'onboarding_complete':True,'live_enabled':True})
                        from .scheduler import install
                        try:
                            installed=install(store,repo)
                            start_cycle()
                            result={'message':'Automatic applications enabled; six-hour schedule installed: '+installed+'. First cycle started.'}
                        except Exception as e:
                            store.update_settings({'live_enabled':False})
                            result={'message':'Facts saved, but scheduling failed. Submissions paused. Run hireme daemon or fix the scheduler: '+str(e)}
                    elif path=='/api/reconcile':
                        if type(data.get('submitted')) is not bool:raise ValueError('Choose submitted or not submitted')
                        store.reconcile(data['id'],data['submitted'],data['note']);result={'saved':True}
                    elif path=='/api/job':
                        from .discovery import posting
                        job=posting(data['url'],data['company'],data['title'],data['location'],'user',data.get('description',''))
                        store.upsert_job(job);result={'id':job['id']}
                    elif path=='/api/run':
                        start_cycle();result={'started':True}
                    else:return self.send(404,{'error':'Not found'})
                    return self.send(200,result)
                finally:store.close()
            except (ValueError,KeyError,TypeError) as e:return self.send(400,{'error':str(e)})
            except Exception as e:return self.send(500,{'error':type(e).__name__})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'Dashboard: http://127.0.0.1:{port}/#token={token}',flush=True)
    try:server.serve_forever()
    finally:server.server_close()
