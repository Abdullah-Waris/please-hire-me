from __future__ import annotations

import contextlib
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from .answers import resolve,REFUSE
from .discovery import ATS_HOSTS,PORTAL_HOSTS
from .util import Blocked,digest,private_dir,public_host,safe_document

UPLOAD_HOSTS={'grnhse-prod-jben-us-west-2.s3.us-west-2.amazonaws.com',
              'grnhse-prod-jben-us-east-1.s3.us-east-1.amazonaws.com',
              'grnhse-prod-jben-eu-west-1.s3.eu-west-1.amazonaws.com'}
CONTROLS='input:not([type=hidden]):not([type=submit]):not([type=button]),textarea,select,[role=combobox]:not(input):not(select)'
SNAPSHOT=r"""selector => {
 const controls=Array.from(document.querySelectorAll(selector)); const out=[]; const seen=new Set();
 function labelText(n) {
  if(!n)return '';const copy=n.cloneNode(true);
  copy.querySelectorAll('input,select,textarea,button,[role=combobox]').forEach(x=>x.remove());
  return copy.textContent.trim();
 }
 function reference(el) {return {id:el.id||'',name:el.name||'',tag:el.tagName.toLowerCase()};}
 function label(el) {
  const ids=(el.getAttribute('aria-labelledby')||'').split(/\s+/).filter(Boolean);
  const aria=ids.map(id=>document.getElementById(id)?.innerText||'').join(' ').trim();
  const direct=Array.from(el.labels||[]).map(labelText).join(' ').trim();
  const field=el.closest('fieldset'); const legend=field?.querySelector('legend')?.innerText;
  const wrapper=el.closest('[class*=form-field],[class*=field-entry],[class*=application-question],.field');
  return (el.getAttribute('aria-label')||aria||direct||legend||labelText(wrapper?.querySelector('label'))||el.getAttribute('placeholder')||'').trim();
 }
 controls.forEach((el,index)=>{
  if(!el.getClientRects().length && el.type!=='file')return;
  if(el.disabled || el.closest('[aria-hidden=true]') || (el.readOnly && el.tabIndex<0))return;
  let type=el.tagName==='SELECT'?'select':el.tagName==='TEXTAREA'?'textarea':el.getAttribute('role')==='combobox'?'combobox':el.type||'text';
  let indices=[index]; let question=label(el); let options=[]; let value=el.value||'';
  if(type==='file'){
   const identity=(el.id+' '+el.name).toLowerCase();
   if(/transcript/.test(identity))question='Transcript';
   else if(/resume|\bcv\b/.test(identity))question='Resume/CV';
   else if(/cover.?letter/.test(identity))question='Cover letter';
  }
  if(type==='radio'){
   const name=el.name; if(!name||seen.has(name))return;seen.add(name);
   const group=controls.filter(x=>x.type==='radio'&&x.name===name);
   indices=group.map(x=>controls.indexOf(x)); options=group.map(x=>Array.from(x.labels||[]).map(l=>l.innerText).join(' ').trim()||x.value);
   const parent=el.closest('fieldset'); question=parent?.querySelector('legend')?.innerText||el.closest('[class*=field],[class*=question]')?.querySelector('label')?.innerText||question;
   value=group.find(x=>x.checked)?.value||'';
  }else if(type==='select'){options=Array.from(el.options).filter(o=>o.value&&!o.disabled).map(o=>o.textContent.trim())}
  else if(type==='checkbox'){options=['Yes','No'];value=el.checked?'Yes':'No'}
  out.push({index,indices,ref:reference(el),refs:indices.map(i=>reference(controls[i])),label:question.replace(/\s+/g,' ').trim(),type,options,
   required:el.required||el.getAttribute('aria-required')==='true'||/\*/.test(question),
   maxlength:el.maxLength||-1,value,multiple:!!el.multiple});
 });return out;
}"""
CONFIRMED=re.compile(r"thank you for (?:your interest|applying|submitting)|application (?:has been |was )?(?:successfully )?(?:submitted|received)|we (?:have |have successfully )?received your application",re.I)
LOGIN=re.compile(r"sign in to (?:apply|continue)|log in to (?:apply|continue)|create (?:an |your )account|verify your (?:email|identity)|enter (?:the |your )?(?:verification|one.time|security) code",re.I)


class Browser:
    def __init__(self,store,test_url=None):
        self.store=store; self.test_url=test_url; self.context=None; self.playwright=None
        self.page=None; self.aid=None; self.attempted=False; self.current_host=""; self.host_cache={}; self.denied_write=False; self.upload_payloads={}; self.uploaded_files=set()

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.playwright=sync_playwright().start()
        s=self.store.settings(); profile=private_dir(self.store.root/"browser")
        kwargs={"headless":s["headless"],"accept_downloads":False,"service_workers":"block"}
        if s["browser_channel"]=="chrome": kwargs["channel"]="chrome"
        try:self.context=self.playwright.chromium.launch_persistent_context(str(profile),**kwargs)
        except Exception:
            self.playwright.stop(); raise Blocked("browser_unavailable","Install Chrome or choose Chromium in settings; close the dedicated sign-in window")
        self.context.set_default_timeout(15000)
        self.context.route("**/*",self._route)
        self.page=self.context.pages[0] if self.context.pages else self.context.new_page()
        for p in self.context.pages:
            if p!=self.page:p.close()
        self.context.on("page",lambda p:p.close() if p!=self.page else None)
        self.page.on("response",self._upload_response)
        self.page.on("dialog",lambda d:d.dismiss())
        self.page.on("download",lambda d:d.cancel())
        return self

    def __exit__(self,*exc):
        if self.context:
            with contextlib.suppress(Exception):self.context.close()
        if self.playwright:self.playwright.stop()

    def _route(self,route):
        url=route.request.url; p=urlsplit(url)
        if self.test_url and url.startswith(self.test_url):return route.continue_()
        host=p.hostname
        if p.scheme!="https" or not host or p.port not in (None,443):return route.abort()
        if host not in self.host_cache:self.host_cache[host]=public_host(host)
        if not self.host_cache[host]:return route.abort()
        if host in UPLOAD_HOSTS:
            payload=getattr(route.request,'post_data_buffer',None) or b''
            approved=self.current_host in {'boards.greenhouse.io','job-boards.greenhouse.io','boards.eu.greenhouse.io','job-boards.eu.greenhouse.io'} and route.request.method=='POST' and any(data in payload or h.encode() in payload for h,data in self.upload_payloads.items())
            return route.continue_() if approved else route.abort()
        # No arbitrary website can receive personal values through an injected pixel or redirect.
        asset_hosts={"www.google.com","www.gstatic.com","fonts.googleapis.com","fonts.gstatic.com",
          "www.recaptcha.net","recaptcha.google.com","cdn.jsdelivr.net","cdnjs.cloudflare.com",
          "static.ashbyhq.com","api.ashbyhq.com","app.ashbyhq.com","cdn.ashbyprd.com","storage.googleapis.com","cdn.greenhouse.io",
          "job-boards.cdn.greenhouse.io","job-boards.eu.cdn.greenhouse.io",
          "boards-api.greenhouse.io","boards.cdn.greenhouse.io","email-address-validator.us.greenhouse.io","email-address-validator.eu.greenhouse.io","api.lever.co","static.lever.co",
          "cdn.lever.co","lever-client-assets.s3.amazonaws.com","lever-client-logos.s3.us-west-2.amazonaws.com",
          "assets.workable.com","apply.workable.com"}
        recruiting_asset=bool(re.fullmatch(r"s[0-9]+-recruiting\.cdn\.greenhouse\.io",host))
        family={self.current_host}
        if 'greenhouse.io' in self.current_host:family|={'boards.greenhouse.io','job-boards.greenhouse.io','boards.eu.greenhouse.io','job-boards.eu.greenhouse.io'}
        if host not in family|asset_hosts and not recruiting_asset:return route.abort()
        # Pages may read their standard assets; form writes stay on the current ATS family.
        if route.request.method not in ("GET","HEAD","OPTIONS"):
            allowed={self.current_host}
            if self.current_host in {"boards.greenhouse.io","job-boards.greenhouse.io","boards.eu.greenhouse.io","job-boards.eu.greenhouse.io"}:
                allowed|={"boards-api.greenhouse.io","boards.greenhouse.io","job-boards.greenhouse.io"}
            if self.current_host=="jobs.ashbyhq.com":allowed|={"api.ashbyhq.com","storage.googleapis.com"}
            if self.current_host in {"jobs.lever.co","jobs.eu.lever.co"}:allowed|={"api.lever.co"}
            # CAPTCHA endpoints may evaluate passive scoring, but no challenge solving is attempted.
            allowed|={"www.google.com","www.recaptcha.net","recaptcha.google.com"}
            if host not in allowed:return route.abort()
            if not self.attempted and host not in {"www.google.com","www.recaptcha.net","recaptcha.google.com"}:
                payload=route.request.post_data or ""
                reading=False
                try:
                    data=json.loads(payload)
                    queries=data if isinstance(data,list) else [data]
                    reading=all(isinstance(q,dict) and isinstance(q.get('query'),str) and re.match(r'^\s*query\b',q['query']) for q in queries)
                except (ValueError,TypeError):pass
                # Upload-only requests are permitted on known ATS upload paths, never arbitrary mutations.
                reading=reading or p.path=='/uncacheable_attributes/presigned_fields'
                passive_check=p.path.startswith("/cdn-cgi/challenge-platform/")
                uploading=bool(re.search(r'/(?:upload|uploads|files|attachments|documents)(?:/|\?|$)',p.path,re.I))
                if not reading and not uploading and not passive_check:
                    self.denied_write=True
                    return route.abort()
        return route.continue_()

    def _upload_response(self,response):
        request=response.request
        if request.method!='POST' or urlsplit(request.url).hostname not in UPLOAD_HOSTS or not 200<=response.status<300:return
        payload=request.post_data_buffer or b''
        for h,data in self.upload_payloads.items():
            if data in payload or h.encode() in payload:self.uploaded_files.add(h)

    def _wait_ready(self):
        self.page.wait_for_function("""() => document.body &&
          !document.querySelector('[aria-busy="true"]') &&
          (document.querySelector('form,input:not([type=hidden]),textarea,select') ||
           Array.from(document.querySelectorAll('a,button')).some(e=>/^apply/i.test(e.textContent.trim())) ||
           /no longer|expired|sign in|log in|captcha/i.test(document.body.innerText))""",timeout=20000)
        # Network idle is a bounded hydration aid, not a requirement on analytics-heavy sites.
        with contextlib.suppress(Exception):self.page.wait_for_load_state('networkidle',timeout=4000)

    def _guard(self,job):
        if self.denied_write:raise Blocked("unapproved_draft_write","An unsupported page attempted to save data before submit authorization")
        url=self.page.url; host=urlsplit(url).hostname
        if self.test_url and url.startswith(self.test_url):pass
        elif host!=self.current_host:
            raise Blocked("unexpected_redirect",url)
        if self.page.locator('input[type=password]').count():raise Blocked("account_blocked")
        if self.page.locator('iframe[src*="bframe"],iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare.com"]').count():
            raise Blocked("captcha_blocked")
        text=self.page.locator('body').inner_text(timeout=5000)
        if re.search(r"(?:job|position|posting).{0,40}(?:no longer available|no longer accepting|has expired|has been filled)",text,re.I):raise Blocked("expired_posting")
        if LOGIN.search(text):raise Blocked("account_or_verification_blocked")
        if REFUSE.search(text):raise Blocked("human_work_sample")
        return text

    def _snapshot(self):
        fields=self.page.evaluate(SNAPSHOT,CONTROLS)
        # Custom dropdown option enumeration is a read task, before any personal value is filled.
        for f in fields:
            if f['type']=='combobox':
                el=self._control(f)
                try:
                    el.click(); self.page.wait_for_timeout(200)
                    menu=self._menu(el)
                    f['options']=[x.strip() for x in menu.get_by_role('option').all_text_contents() if x.strip()]
                    selected=[x.strip() for x in menu.get_by_role('option',selected=True).all_text_contents() if x.strip()]
                    if len(selected)==1:f['value']=selected[0]
                    elif not f['value']:
                        f['value']=el.evaluate("""e=>{
                          for(let n=e.parentElement,depth=0;n&&depth<5;n=n.parentElement,depth++){
                            const values=n.querySelectorAll('[class*=singleValue],[class*=single-value]');
                            if(values.length===1){
                              const flag=values[0].querySelector('[class*=iti__flag]');
                              const code=flag&&Array.from(flag.classList).find(c=>/^iti__[a-z]{2}$/.test(c));
                              if(code){
                                const menu=document.getElementById(e.getAttribute('aria-controls'));
                                const options=Array.from((menu||document).querySelectorAll('[role=option]')).filter(o=>o.getClientRects().length&&o.querySelector('.'+code));
                                if(options.length===1)return options[0].textContent.trim();
                              }
                              return values[0].textContent.trim();
                            }
                          }return e.textContent.trim();}""")
                    el.press('Escape')
                except Exception:raise Blocked('unsupported_widget',f['label'])
        return fields

    @staticmethod
    def _shape(fields):
        return [{k:v for k,v in f.items() if k not in ('value','index','indices','ref','refs')} for f in fields]

    def _menu(self, el):
        for name in ('aria-controls','aria-owns'):
            ident=el.get_attribute(name)
            if ident:
                menu=self.page.locator('[id='+json.dumps(ident.split()[0])+']')
                if menu.count()==1:return menu
        return self.page

    def _control(self, field, option=None):
        ref=field.get('refs',[field.get('ref',{})])[option] if option is not None else field.get('ref',{})
        if ref.get('id'):
            locator=self.page.locator('[id='+json.dumps(ref['id'])+']')
            if locator.count()==1:return locator
        if ref.get('name'):
            locator=self.page.locator(ref.get('tag','input')+'[name='+json.dumps(ref['name'])+']')
            if locator.count()==1:return locator
        # Reacquire anonymous controls by current semantic shape instead of stale indices.
        fresh=self.page.evaluate(SNAPSHOT,CONTROLS)
        matches=[f for f in fresh if f['label']==field['label'] and f['type']==field['type']]
        if len(matches)!=1:raise Blocked('form_changed',field['label'])
        index=matches[0]['indices'][option] if option is not None else matches[0]['index']
        return self.page.locator(CONTROLS).nth(index)

    def _application_scope(self, answers):
        forms=set()
        for answer in answers:
            if answer['provenance'].get('fact_key') not in {'email','full_name','first_name','last_name'}:continue
            owner=self._control(answer['field']).locator('xpath=ancestor::form[1]')
            if owner.count()==1:forms.add(owner.evaluate('(e)=>Array.from(document.forms).indexOf(e)'))
        if len(forms)>1:raise Blocked('unsupported_form','Applicant controls belong to different forms')
        return self.page.locator('form').nth(next(iter(forms))) if forms else self.page

    def _fill(self,answer):
        f=answer['field']; value=answer['value']; controls=self.page.locator(CONTROLS)
        el=self._control(f)
        if f['type']=='select':el.select_option(label=value)
        elif f['type']=='radio':self._control(f,f['options'].index(value)).check()
        elif f['type']=='checkbox':el.set_checked(value=='Yes')
        elif f['type']=='combobox':
            el.click()
            if el.evaluate('(e)=>e.tagName==="INPUT"'):el.fill(value)
            self._menu(el).get_by_role('option',name=value,exact=True).click()
        else:
            if f['type']!='textarea' and '\n' in value:raise Blocked('invalid_single_line_answer',f['label'])
            el.fill(value)

    def _verify(self,answers,documents,fields):
        fresh=self._snapshot()
        body=self.page.locator('body').inner_text()
        completed={d['field']['label'] for d in documents if d['hash'] in self.uploaded_files and d['filename'] in body}
        def remaining(items):return [f for f in items if not (f['type']=='file' and f['label'] in completed)]
        if digest(self._shape(remaining(fresh)))!=digest(self._shape(remaining(fields))):raise Blocked('form_changed')
        for a in answers:
            f=a['field']; el=self._control(f); value=a['value']
            if f['type']=='select':actual=el.locator('option:checked').inner_text().strip()
            elif f['type']=='radio':
                actual=next((f['options'][i] for i,index in enumerate(f['indices']) if self._control(f,i).is_checked()),'')
            elif f['type']=='checkbox':actual='Yes' if el.is_checked() else 'No'
            elif f['type']=='combobox':actual=next((x['value'] for x in fresh if x['label']==f['label'] and x['type']=='combobox'),'')
            else:actual=el.input_value()
            if a['provenance'].get('fact_key')=='phone':
                actual=re.sub(r'[^0-9]','',actual);value=re.sub(r'[^0-9]','',value)
            if actual!=value:raise Blocked('field_verification_failed',f['label'])
        for d in documents:
            if d['hash'] in self.uploaded_files and d['filename'] in body:continue
            el=self._control(d['field'])
            sizes=el.evaluate('(e)=>Array.from(e.files||[]).map(f=>f.size)')
            expected=safe_document(self.store.root/'documents'/d['filename'],self.store.root/'documents').stat().st_size
            if sizes!=[expected] and not (d['hash'] in self.uploaded_files and d['filename'] in self.page.locator('body').inner_text()):raise Blocked('upload_verification_failed')
        if self.page.locator('[aria-invalid=true]').count() or not self.page.evaluate('() => Array.from(document.forms).every(f=>f.checkValidity())'):raise Blocked('invalid_fields')

    def apply(self,job,live=True):
        self.aid=None; self.attempted=False; self.denied_write=False; self.upload_payloads={}; self.uploaded_files=set()
        self.current_host=job['host']
        if self.test_url:self.current_host=urlsplit(self.test_url).hostname
        elif job['host'] not in ATS_HOSTS|PORTAL_HOSTS:raise Blocked('unapproved_destination')
        self.page.goto(job['url'],wait_until='domcontentloaded',timeout=45000)
        self._wait_ready()
        text=self._guard(job)
        # Portal host registration is not proof of a session; inspect the current page too.
        if job['host'] in PORTAL_HOSTS and job['host'] not in self.store.settings()['signed_in_portals'] and job['host'] not in {'www.deshaw.com','explore.jobs.netflix.net','career.mlp.com','jobs.uber.com','www.rentec.com'}:
            raise Blocked('account_blocked','Sign in through the dedicated browser and register this portal')
        # Read the actual posting again before policy checks: list feeds are not eligibility proof.
        from .policy import eligible
        job={**job,'description':text,'answer_scope':job['host']+'|'+self.store.company(job['company'])}
        eligible(job,self.store.settings(),self.store.facts())
        self.store.upsert_job(job)
        all_answers=[]; all_docs=[]; steps=[]
        for step in range(8):
            self._guard(job)
            fields=self._snapshot()
            if not fields:
                apply=self.page.get_by_role('button',name=re.compile(r'^(?:apply(?: now| for this job)?|application)$',re.I))
                if apply.count()!=1:apply=self.page.get_by_role('link',name=re.compile(r'^(?:apply(?: now| for this job)?|application)$',re.I))
                if apply.count()!=1 or apply.evaluate('(e)=>!!e.closest("form")'):raise Blocked('unsupported_form','No unambiguous navigation-only application entry')
                apply.click();self._wait_ready();continue
            answers=[]; documents=[]; pending=[]
            for f in fields:
                if not f['label']:
                    if f['required']:raise Blocked('unlabeled_required_field')
                    continue
                if f['type']=='file':
                    kind='transcript' if re.search(r'transcript',f['label'],re.I) else 'resume' if re.search(r'resume|cv',f['label'],re.I) else None
                    doc=self.store.db.execute('SELECT * FROM documents WHERE kind=?',(kind,)).fetchone()
                    if not doc:
                        if f['required']:pending.append((f,'missing_document'))
                        continue
                    documents.append({**dict(doc),'field':f});continue
                try:
                    from .provider import LazyProvider
                    provider=LazyProvider(self.store.settings()['model_timeout_seconds'])
                    a=resolve(self.store,job['answer_scope'],f,provider,context={**job,'form_questions':[x['label'] for x in fields],'previous_templates':[x['provenance']['template_id'] for x in answers if 'template_id' in x['provenance']]})
                    if a:answers.append(a)
                    elif f['value']:raise Blocked('unknown_prefilled_value',f['label'])
                except Blocked as e:
                    if e.reason=='human_work_sample':raise
                    if not f['required'] and not f['value']:
                        self.store.resolve_known_question(job['answer_scope'],f['label']);continue
                    self.store.ask(job['id'],job['answer_scope'],f['label'],f['options'],e.reason)
                    pending.append((f,e.reason))
            if pending:raise Blocked('missing_answers','; '.join(f['label'] for f,_ in pending))
            for d in documents:
                path=safe_document(self.store.root/'documents'/d['filename'],self.store.root/'documents')
                if hashlib.sha256(path.read_bytes()).hexdigest()!=d['hash']:raise Blocked('document_tampered')
                self.upload_payloads[d['hash']]=path.read_bytes()
                self._control(d['field']).set_input_files(str(path))
            if documents:
                with contextlib.suppress(Exception):self.page.wait_for_load_state('networkidle',timeout=8000)
            for a in answers:self._fill(a)
            self._verify(answers,documents,fields)
            self._guard(job)
            all_answers.extend(answers);all_docs.extend(documents)
            steps.append({'step':step,'fields':fields,'url':self.page.url})
            scope=self._application_scope(answers)
            submit=scope.get_by_role('button',name=re.compile(r'^(submit(?: application)?|send application|apply|finish|review & apply)$',re.I))
            if submit.count()!=1:
                nxt=scope.get_by_role('button',name=re.compile(r'^(next|continue|save and continue)$',re.I))
                if nxt.count()!=1:raise Blocked('unsupported_submit','No unique final submit or next button')
                # Save durable draft Q&A before any portal step may save data remotely.
                self.store.event('draft_step',job['id'],{'answers':answers,'documents':documents,'url':self.page.url})
                raise Blocked('multi_step_requires_adapter','This portal step can save data remotely; finish through the dashboard job link')
            package={'job_id':job['id'],'url':job['url'],'answers':all_answers,'documents':all_docs,
                     'facts_hash':digest(self.store.facts()),'steps':steps}
            self.aid=self.store.prepare(job,package)
            before=private_dir(self.store.root/'screenshots')/(self.aid+'-before.jpg')
            self.page.screenshot(path=str(before),type='jpeg',full_page=True)
            if not live:return 'prepared'
            if not submit.is_enabled():raise Blocked('submit_disabled')
            # The committed intent is immediately before the only final click.
            self._guard(job)
            self._verify(answers,documents,fields)
            self.store.begin_submit(self.aid); self.attempted=True
            try:
                submit.click(timeout=15000)
                self.page.wait_for_timeout(1200)
                text=self._guard(job)
                screenshot=self.store.root/'screenshots'/(self.aid+'-after.jpg')
                self.page.screenshot(path=str(screenshot),type='jpeg',full_page=True)
                confirmed=CONFIRMED.search(text) and not self.page.locator('input[type=email]').count()
                self.store.finish(self.aid,'confirmed' if confirmed else 'unknown',text[:4000],screenshot.name)
                return 'confirmed' if confirmed else 'unknown'
            except Exception as e:
                outcome=self.store.db.execute('SELECT state FROM applications WHERE id=?',(self.aid,)).fetchone()
                if outcome and outcome[0]=='submitting':self.store.finish(self.aid,'unknown',f'{type(e).__name__}: outcome requires verification')
                raise Blocked('submission_unknown')
        raise Blocked('unsupported_form','Step limit reached')
