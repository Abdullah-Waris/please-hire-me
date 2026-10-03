let materialOffset=0;
'use strict';
const token=new URLSearchParams(location.hash.slice(1)).get('token')||sessionStorage.getItem('hireme-token')||'';
if(token)sessionStorage.setItem('hireme-token',token);
history.replaceState(null,'',location.pathname);
let state=null,view='today';
function renderAccounts(){
  const parent=document.querySelector('#employer-accounts');parent.replaceChildren();
  const accounts=state.employer_accounts||[];
  if(!accounts.length)return empty(parent,'No employer accounts created by this worker.');
  for(const account of accounts){
    const box=el('article',undefined,'question');
    box.append(el('h3',account.company),el('p',`${account.origin} · ${account.state}`));
    if(account.state==='uncertain'){
      const form=el('form'),evidence=el('textarea');evidence.required=true;evidence.minLength=10;evidence.maxLength=2000;evidence.rows=2;
      evidence.setAttribute('aria-label',`Account confirmation evidence for ${account.company}`);
      evidence.placeholder='How did you verify that this account exists and you can sign in?';
      form.append(evidence,el('button','Confirm verified account'));
      form.onsubmit=async event=>{event.preventDefault();try{await api('/api/account-confirm',{id:account.id,note:evidence.value});await refresh();note('Account confirmed. The next batch can reuse its credentials.');}catch(error){note(error.message,true);}};
      box.append(form);
    }
    parent.append(box);
  }
}
const $=s=>document.querySelector(s);
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const note=(text,error=false)=>{$('#notice').textContent=text;$('#notice').classList.toggle('error',error);};
async function api(path,data,raw=false,extraHeaders={}){const r=await fetch(path,{method:data===undefined?'GET':'POST',headers:{...extraHeaders,'X-Hireme-Token':token,...(!raw&&data!==undefined?{'Content-Type':'application/json'}:{})},body:data===undefined?undefined:raw?data:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw new Error(v.error||'Request failed');return v;}
function show(name){view=name;document.querySelectorAll('.view').forEach(n=>n.hidden=n.id!==name);document.querySelectorAll('[data-view]').forEach(n=>n.setAttribute('aria-current',n.dataset.view===name?'page':'false'));$('#heading').textContent={setup:'Make it yours',providers:'Your model connection',today:'Today’s applications',questions:'A few things need you',profile:'Your verified facts',materials:'Your writing and context',connections:'Email automation',settings:'Your search preferences'}[name];$('#subheading').textContent={setup:'Set up once. Save as you go.',providers:'Choose who processes your application context.',today:'A real record of what the worker submitted, held and discovered.',questions:'Resolve the exception. Let the next cycle do the rest.',profile:'Saved once, reused across applications. Unknown means unknown.',materials:'Reviewed sources guide the voice and facts in your applications.',connections:'Verification codes and batch reports for your application email.',settings:'Choose your search boundaries. Throughput never overrides them.'}[name];}
function link(url,text){const a=el('a',text);if(/^https:\/\//.test(url)){a.href=url;a.target='_blank';a.rel='noopener noreferrer';}return a;}
function date(v){return v?new Date(v).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}):'—';}
function empty(parent,text){parent.append(el('p',text,'empty'));}
function table(jobs,parent){parent.replaceChildren();if(!jobs.length)return empty(parent,'Nothing here yet. Jobs appear after discovery; blocked opportunities stay available for you.');const t=el('table'),head=el('thead'),hr=el('tr');['Opportunity','State','Fit','Record'].forEach(x=>hr.append(el('th',x)));head.append(hr);t.append(head);const body=el('tbody');for(const job of jobs){const row=el('tr'),a=el('td');a.append(link(job.url,job.title));a.firstChild.className='job-title';a.append(el('p',`${job.company} · ${JSON.parse(job.payload).location||'Location not stated'}`));if(job.reason)a.append(el('p',job.reason));const b=el('td');b.append(el('span',job.status==='confirmed'?'Submitted':job.status.replaceAll('_',' '),'state '+job.status));const c=el('td',String(job.score));const d=el('td');const app=state.applications.find(x=>x.job_id===job.id);if(app){const detail=el('details');detail.append(el('summary','Answers & evidence'));const list=el('ul',undefined,'answer-log');for(const answer of JSON.parse(app.package).answers){const li=el('li');li.append(el('strong',answer.field.label),el('p',answer.value),el('small',answer.provenance.fact_key?`Verified fact: ${answer.provenance.fact_key}`:answer.provenance.sample_parts?'Your approved writing samples':answer.provenance.template_id?'Your approved writing sample':answer.provenance.resume_quote?'Verified resume evidence':answer.provenance.job_source?'Recorded discovery source':answer.provenance.contextual_preference?'Selected from your confirmed skills and availability':answer.provenance.job_title?'Role from this posting':'Your saved answer'));list.append(li);}detail.append(list);if(app.screenshot){const btn=el('button','View confirmation','secondary');btn.type='button';btn.onclick=async()=>{try{const r=await fetch('/api/screenshot/'+encodeURIComponent(app.screenshot),{headers:{'X-Hireme-Token':token}});if(!r.ok)throw new Error('Screenshot unavailable');const img=el('img');const url=URL.createObjectURL(await r.blob());img.src=url;img.alt='Recorded page after submission';img.className='evidence';img.onload=()=>URL.revokeObjectURL(url);btn.replaceWith(img);}catch(e){note(e.message,true);}};detail.append(btn);}d.append(detail);}else d.append(el('span','Not submitted','subtle'));row.append(a,b,c,d);body.append(row);}t.append(body);parent.append(t);}
function renderQuestions(){const q=$('#question-list');q.replaceChildren();if(!state.questions.length)empty(q,'No unanswered personal questions. New questions will appear here without stopping the rest of the search.');for(const x of state.questions){const box=el('article',undefined,'question');box.append(el('h3',x.label));const job=state.jobs.find(j=>j.id===x.job_id);if(job)box.append(link(job.url,`${job.company} · ${job.title}`));box.append(el('p',x.reason,'subtle'));const f=el('form');const options=JSON.parse(x.options);const input=options.length?el('select'):el('textarea');input.required=true;input.setAttribute('aria-label',x.label);if(options.length){input.append(new Option('Choose an answer',''));options.forEach(v=>input.append(new Option(v,v)));}else input.rows=3;const bind=el('select');bind.setAttribute('aria-label','Optional confirmed fact');bind.append(new Option('Save as an exact answer to this question',''));for(const [k,v] of Object.entries(state.facts)){if(v.confirmed)bind.append(new Option(`Use ${state.fact_labels[k]}: ${v.value}`,k));}bind.onchange=()=>{if(bind.value)input.value=state.facts[bind.value].value;};const b=el('button','Save once and reuse');f.append(input,bind,b);f.onsubmit=async e=>{e.preventDefault();try{await api('/api/answer',{id:x.id,value:input.value,fact_key:bind.value||null});note('Answer saved. Matching applications can use it in the next cycle.');await refresh();}catch(e){note(e.message,true);}};box.append(f);q.append(box);}table(state.jobs.filter(j=>j.status==='blocked'),$('#blocked-jobs'));const u=$('#uncertain');u.replaceChildren();const unknown=state.applications.filter(a=>['unknown','awaiting_verification'].includes(a.state));if(!unknown.length)empty(u,'No uncertain submissions.');for(const a of unknown){const box=el('article',undefined,'question');const job=state.jobs.find(j=>j.id===a.job_id);box.append(el('h3',job?`${job.company} · ${job.title}`:a.job_id));if(job)box.append(link(job.url,'Verify at the employer'));if(a.state==='awaiting_verification')box.append(el('p','Email verification pending. This application is held and will not be retried automatically.','subtle')); const f=el('form'),select=el('select');select.setAttribute('aria-label','Verified outcome');select.append(new Option('Employer confirms submission','true'),new Option('Verified no submission occurred','false'));const text=el('textarea');text.required=true;text.minLength=10;text.rows=2;text.placeholder='How did you verify the outcome?';text.setAttribute('aria-label','Verification evidence');const b=el('button','Record verified outcome');f.append(select,text,b);f.onsubmit=async e=>{e.preventDefault();try{await api('/api/reconcile',{id:a.id,submitted:select.value==='true',note:text.value});await refresh();note('Outcome recorded. A non-submitted attempt remains held for manual handling.');}catch(e){note(e.message,true);}};box.append(f);u.append(box);}}
const groups={ 'Contact':['full_name','first_name','last_name','preferred_name','email','phone','location','street','city','state','postal_code','country','linkedin','github','website'], 'Education & experience':['school','high_school','degree','major','graduation','college_start','highest_completed_degree','gpa','professional_years','skills'], 'Authorization & availability':['work_authorized_us','needs_sponsorship','citizenship','us_person','unrestricted_authorization','earliest_start','latest_start','salary','notice_period','relocate','onsite','summer_2027_relocate','worked_outside_resume','contacts_outside_resume'], 'Optional disclosures & consent':['race','gender','veteran','disability','recording','background_check','sms','native_name']};
function renderFacts(){const parent=$('#fact-fields');parent.replaceChildren();for(const [name,keys] of Object.entries(groups)){const group=el('fieldset',undefined,'fact-group');group.append(el('legend',name));const grid=el('div',undefined,'form-grid');for(const key of keys){const label=el('label',state.fact_labels[key]+(state.required.includes(key)?' · required':''));const input=el('input');input.name=key;input.value=state.facts[key]?.value||'';if(state.required.includes(key))input.required=true;if(state.facts[key]&&!state.facts[key].confirmed)label.append(el('span','Extracted from resume — please confirm','candidate'));label.append(input);grid.append(label);}group.append(grid);parent.append(group);}$('#resume-state').textContent=state.documents.some(x=>x.kind==='resume')?'Resume imported and stored privately.':'No resume imported.';$('#transcript-state').textContent=state.documents.some(x=>x.kind==='transcript')?'Transcript imported and stored privately. Upload another PDF to replace it.':'No transcript imported. Jobs requiring one will appear in Needs you.';$('#setup-status').textContent=state.missing_setup.length?'Still needed: '+state.missing_setup.map(k=>state.fact_labels[k]||k).join(', '):'Required facts are confirmed. You can start automatic applications.';$('#complete-setup').disabled=state.missing_setup.length>0;}
function renderTemplates(){const p=$('#templates');p.replaceChildren();for(const t of state.templates){const d=el('details');d.append(el('summary',t.category+' · '+t.body.slice(0,70)),el('p',t.body));p.append(d);}}
function renderSettings(){const f=$('#settings-form');for(const input of f.elements){if(!input.name)continue;const v=state.settings[input.name];if(input.type==='checkbox'){input.checked=!!v;continue;}input.value=Array.isArray(v)?v.join('\n'):typeof v==='object'?JSON.stringify(v,null,2):v;}}
function render(){const today=new Intl.DateTimeFormat('en-CA',{timeZone:state.settings.timezone}).format(new Date());const submitted=state.applications.filter(a=>a.state==='confirmed'&&a.attempted&&new Intl.DateTimeFormat('en-CA',{timeZone:state.settings.timezone}).format(new Date(a.attempted))===today);$('#daily-progress').textContent=`${submitted.length} confirmed today · ${Math.max(0,state.settings.target_per_day-submitted.length)} below target` ;$('#daily-target').textContent=`Daily target: ${state.settings.target_per_day}`;$('#setup-callout').hidden=state.settings.onboarding_complete;$('#worker-state').textContent=state.worker_running?(state.settings.live_enabled?'Cycle running':'Pausing active cycle…'):!state.settings.onboarding_complete?'Setup needed':state.settings.live_enabled?'Automatic submissions enabled':'Submissions paused';$('#pause').textContent=state.settings.live_enabled?'Pause':'Resume';$('#pause').disabled=!state.settings.onboarding_complete;$('#run').disabled=state.worker_running||!state.settings.onboarding_complete||!state.settings.live_enabled;$('#question-count').textContent=state.questions.length?String(state.questions.length):'';const filter=$('#status-filter').value;table(state.jobs.filter(j=>filter==='all'||j.status===filter),$('#jobs'));renderSetup();renderQuestions();renderAccounts();renderTemplates();renderMaterials();renderMail();if(!document.activeElement.closest('#facts-form'))renderFacts();if(!document.activeElement.closest('#settings-form'))renderSettings();const r=$('#runs');r.replaceChildren();if(!state.runs.length)empty(r,'No cycles yet. Finish setup to start the worker.');for(const run of state.runs){const row=el('div',undefined,'run-row');let detail=run.detail;try{const d=JSON.parse(detail);detail=`${d.confirmed||0} confirmed; ${d.attempts||0} attempted. ${d.target===undefined?'':`Target ${d.target}; shortfall ${d.shortfall}. `}${Object.entries(d.outcomes||{}).filter(([k])=>k!=='confirmed').map(([k,v])=>`${k}: ${v}`).join('; ')} ${d.reason||Object.entries(d.reasons||{}).map(([k,v])=>`${k}: ${v}`).join('; ')}`;}catch{}row.append(el('span',date(run.started)),el('span',run.status),el('span',detail));r.append(row);}const s=$('#sources');s.replaceChildren();for(const source of state.sources)s.append(el('p',`${source.id}: ${source.status} · ${date(source.checked)}${source.error?' · '+source.error:''}`));show(view);}
async function refresh(){try{state=await api('/api/state?material_offset='+materialOffset);render();}catch(e){note(e.message,true);}}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>show(b.dataset.view));$('#setup-link').onclick=()=>show('setup');$('#status-filter').onchange=render;
$('#facts-form').onsubmit=async e=>{e.preventDefault();if(!$('#confirm-facts').checked)return;const facts=Object.fromEntries([...new FormData(e.target)].filter(([,v])=>v.trim()));try{await api('/api/facts',{facts});$('#confirm-facts').checked=false;note('Confirmed facts saved. They will be reused automatically.');document.activeElement.blur();await refresh();}catch(e){note(e.message,true);}};
$('#resume-upload').onchange=async e=>{const f=e.target.files[0];if(!f)return;try{await api('/api/resume',f,true);note('Resume imported. Confirm its extracted values and supply the remaining facts.');await refresh();}catch(e){note(e.message,true);}};
$('#settings-form').onsubmit=async e=>{e.preventDefault();const data={};for(const input of e.target.elements){if(!input.name)continue;if(input.type==='checkbox')data[input.name]=input.checked;else if(input.type==='number')data[input.name]=Number(input.value);else if(input.name==='company_aliases')data[input.name]=JSON.parse(input.value||'{}');else if(Array.isArray(state.settings[input.name]))data[input.name]=input.value.split('\n').map(v=>v.trim()).filter(Boolean);else data[input.name]=input.value;}try{await api('/api/settings',data);note('Search preferences saved.');document.activeElement.blur();await refresh();}catch(e){note(e.message,true);}};
$('#complete-setup').onclick=async()=>{try{const r=await api('/api/complete-setup',{start:true});note(r.message||'Automatic applications enabled.');await refresh();}catch(e){note(e.message,true);}};
$('#pause').onclick=async()=>{try{await api(state.settings.live_enabled?'/api/pause':'/api/resume-worker',{});await refresh();}catch(e){note(e.message,true);}};
$('#run').onclick=async()=>{try{await api('/api/run',{});note('Cycle started. You can keep working; the ledger will update.');await refresh();}catch(e){note(e.message,true);}};
$('#job-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/job',Object.fromEntries(new FormData(e.target)));e.target.reset();note('Posting added. Eligibility will be checked before any form is filled.');await refresh();}catch(e){note(e.message,true);}};
refresh().then(()=>{if(state&&!state.settings.onboarding_complete&&view==='today')show('setup');});setInterval(()=>{if(!document.activeElement.matches('input,textarea,select'))refresh();},15000);

$('#template-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/template',Object.fromEntries(new FormData(e.target)));e.target.reset();note('Approved wording saved.');await refresh();}catch(e){note(e.message,true);}};

$('#transcript-upload').onchange=async e=>{const input=e.target,f=input.files[0];if(!f)return;input.disabled=true;try{await api('/api/transcript',f,true);note('Transcript saved. Matching applications can upload it automatically in the next cycle.');await refresh();}catch(error){note(error.message,true);}finally{input.disabled=false;input.value='';}};


function renderMaterials(){
  const list=$('#material-list');
  if(list.contains(document.activeElement))return;
  list.replaceChildren();
  if(state.material_count>20){const controls=el('div',undefined,'actions'),previous=el('button','Newer sources','secondary'),next=el('button','Older sources','secondary');previous.disabled=materialOffset===0;next.disabled=materialOffset+20>=state.material_count;previous.onclick=async()=>{materialOffset=Math.max(0,materialOffset-20);await refresh();};next.onclick=async()=>{materialOffset+=20;await refresh();};controls.append(previous,el('p',`${materialOffset+1}–${Math.min(materialOffset+20,state.material_count)} of ${state.material_count}`),next);list.append(controls);}
  if(!state.materials.length)return empty(list,'Upload a writing sample, cover-letter example or supporting document to begin. Each source gets a review before the model uses it.');
  for(const source of state.materials){
    const box=el('article',undefined,'section');
    box.append(el('h2',source.original_name),el('p',`${source.kind.replaceAll('_',' ')} · ${source.confirmed?'Approved':'Needs review'} · ${date(source.updated)}`,'subtle'));
    const form=el('form',undefined,'material-review');
    const textLabel=el('label','Reviewed excerpt');
    const text=el('textarea');text.rows=8;text.required=true;text.minLength=20;text.maxLength=12000;text.value=source.text;
    textLabel.append(text);
    const roleLabel=el('label','How the model can use this');
    const role=el('select');
    role.append(new Option('Background reference — no claim that I did this work','reference'),new Option('My own factual work and experience','personal'),new Option('Writing style and structure only','style'));
    role.value=source.role;roleLabel.append(role);
    const approvedLabel=el('label',undefined,'confirmation');const approved=el('input');approved.type='checkbox';approved.checked=!!source.confirmed;
    approvedLabel.append(approved,document.createTextNode('I reviewed this excerpt and approve its selected use. Uncheck to stop using it.'));
    const button=el('button','Save reviewed source');
    form.append(textLabel,el('p','Keep up to 12,000 characters per reviewed excerpt. Example qualifications belong in style-only sources unless they describe your own work.','help'),roleLabel,approvedLabel,button);
    form.onsubmit=async event=>{event.preventDefault();button.disabled=true;try{await api('/api/material-review',{id:source.id,text:text.value,role:role.value,confirmed:approved.checked});document.activeElement.blur();await refresh();note('Source saved. Approved use and revisions are recorded.');}catch(error){note(error.message,true);}finally{button.disabled=false;}};
    box.append(form);list.append(box);
  }
}
$('#material-upload-form').onsubmit=async event=>{
  event.preventDefault();const form=event.target,file=form.elements.file.files[0],button=form.querySelector('button');if(!file)return;
  if(file.size>20*1024*1024)return note('Choose a file up to 20 MiB.',true);
  button.disabled=true;
  try{await api('/api/material-upload',file,true,{'X-Upload-Name':encodeURIComponent(file.name),'X-Material-Kind':form.elements.kind.value});form.reset();await refresh();note('Source uploaded. Review the excerpt and choose how the model can use it.');}
  catch(error){note(error.message,true);}finally{button.disabled=false;}
};


function renderMail(){
  const mail=state.gmail;
  $('#gmail-state').textContent=mail.connected?`Authorization saved for ${mail.email}.`:mail.client_configured?'OAuth client saved. Run the connection command below to authorize Gmail.':'No Gmail authorization saved.';
  const form=$('#mail-settings-form');
  if(!form.contains(document.activeElement))for(const input of form.elements){if(input.name)input.checked=!!state.settings[input.name];}
  const reports=$('#report-delivery');reports.replaceChildren();
  if(!state.reports.length)empty(reports,'Batch reports appear here after the worker runs. Email delivery is optional.');
  for(const report of state.reports)reports.append(el('p',`${date(report.created)} · ${report.state}${report.last_error?' · '+report.last_error:''}`));
}
$('#gmail-client-upload').onchange=async event=>{
  const input=event.target,file=input.files[0];if(!file)return;
  if(file.size>65536){input.value='';return note('Choose the Google OAuth client JSON, up to 64 KiB.',true);}
  input.disabled=true;
  try{await api('/api/gmail-client',file,true);await refresh();note('OAuth client stored privately. Run the connection command to authorize Gmail.');}catch(error){note(error.message,true);}finally{input.disabled=false;input.value='';}
};
$('#mail-settings-form').onsubmit=async event=>{
  event.preventDefault();const form=event.target;
  try{await api('/api/settings',{gmail_reports:form.elements.gmail_reports.checked,gmail_verification:form.elements.gmail_verification.checked});document.activeElement.blur();await refresh();note('Email preferences saved.');}catch(error){note(error.message,true);}
};
$('#flush-reports').onclick=async event=>{
  const button=event.target;button.disabled=true;
  try{const result=await api('/api/reports/flush',{});await refresh();note(result.error?`Reports remain queued: ${result.error}`:`${result.sent} report(s) sent.`,!!result.error);}catch(error){note(error.message,true);}finally{button.disabled=false;}
};


const setupSteps=[['Documents','profile','Import your required resume and optional transcript. Cover-letter examples go in Writing & context.'],['Key information','profile','Confirm the facts extracted from your resume. Add authorization and availability yourself.'],['Additional context','materials','Add your own experience or supporting research; choose the correct approved use.'],['Writing samples','materials','Upload essays or cover-letter examples. Style sources guide voice, not qualifications.'],['Job preferences','settings','Choose roles, locations, seniority and exclusions. Save preferences before continuing.'],['Schedule and limits','settings','Choose batch frequency, submission ceilings, attempt ceilings and model request caps. Save preferences.'],['Model and run location','providers','Connect a CLI subscription or a paid API key. Finish paused or start batches.']];
let setupStep=-1;

function renderSetup(){
  const checks=state.readiness,parent=$('#machine-checks');parent.replaceChildren();
  parent.append(el('h2','This machine'),el('p',`${checks.platform} · ${checks.architecture} · Python ${checks.python}`),el('p',`Browser: ${checks.browser_ready?'available':'missing — run setup.sh or install Chromium'} · Model: ${checks.provider.message}`));
  const list=$('#setup-steps');list.replaceChildren();
  setupSteps.forEach(([title,route,description],index)=>{const row=el('div',undefined,'section');const button=el('button',`${index+1}. ${title}`,'secondary');button.onclick=()=>goSetup(index);row.append(button,el('p',description,'help'));list.append(row);});
  const f=$('#provider-form');if(!f.contains(document.activeElement))for(const input of f.elements){if(input.name&&input.name!=='key')input.value=state.settings[input.name];}
  $('#provider-state').textContent=checks.provider.message;
  $('#provider-instructions').textContent=state.settings.provider==='claude-cli'?'claude auth login':state.settings.provider==='codex-cli'?'codex login':'Use your vendor’s console to create a key and select an accessible model ID.';
  $('#finish-paused').disabled=state.missing_setup.length>0;$('#finish-start').disabled=state.missing_setup.length>0;
}
function goSetup(index){setupStep=index;const [title,route,description]=setupSteps[index];$('#guided-setup').hidden=false;$('#guided-label').textContent=`Step ${index+1} of ${setupSteps.length} · ${title}. ${description}`;$('#setup-back').disabled=index===0;$('#setup-next').hidden=index===setupSteps.length-1;show(route);$('#guided-setup').scrollIntoView({block:'start'});}
$('#begin-setup').onclick=()=>goSetup(0);
$('#setup-back').onclick=()=>goSetup(Math.max(0,setupStep-1));
$('#setup-next').onclick=()=>{if(setupStep===0&&!state.documents.some(d=>d.kind==='resume'))return note('Import a resume before continuing.',true);if(setupStep===1&&state.missing_setup.length)return note('Confirm the required facts before continuing: '+state.missing_setup.join(', '),true);goSetup(Math.min(setupSteps.length-1,setupStep+1));};
$('#setup-exit').onclick=()=>{$('#guided-setup').hidden=true;setupStep=-1;show('today');};
$('#provider-form').onsubmit=async event=>{event.preventDefault();const form=event.target;const provider=form.elements.provider.value;try{if(provider.endsWith('-api')&&!form.elements.provider_model.value.trim())throw new Error('Enter an exact model ID for API mode.');if(form.elements.key.value){await api('/api/provider-key',{provider,key:form.elements.key.value});form.elements.key.value='';}await api('/api/settings',{provider,provider_model:form.elements.provider_model.value.trim(),deployment:form.elements.deployment.value});document.activeElement.blur();await refresh();note('Connection saved. Check login before starting.');}catch(error){note(error.message,true);}};
$('#check-provider').onclick=async event=>{event.target.disabled=true;try{const result=await api('/api/provider-check',{});$('#provider-state').textContent=result.provider.message;note(result.provider.message,!result.provider.ready);}catch(error){note(error.message,true);}finally{event.target.disabled=false;}};
$('#remove-provider-key').onclick=async()=>{try{await api('/api/remove-provider-key',{});await refresh();note('Saved API key removed.');}catch(error){note(error.message,true);}};
async function finishSetup(start){try{const result=await api('/api/complete-setup',{start});$('#guided-setup').hidden=true;setupStep=-1;await refresh();show('today');note(result.message);}catch(error){note(error.message,true);}}
$('#finish-paused').onclick=()=>finishSetup(false);$('#finish-start').onclick=()=>finishSetup(true);

$('#context-form').onsubmit=async event=>{event.preventDefault();try{await api('/api/context-text',Object.fromEntries(new FormData(event.target)));event.target.reset();await refresh();note('Approved context saved.');}catch(error){note(error.message,true);}};
