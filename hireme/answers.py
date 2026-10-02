from __future__ import annotations

import json
import re

from .util import Blocked, digest

# These mappings authorize exact values only. Unknown wording is queued, never guessed.
RULES = [
    (r"^(full |legal |full legal )?name\*?$", "full_name"),
    (r"^(legal )?first name\*?$", "first_name"), (r"^(legal )?last name\*?$", "last_name"),
    (r"^preferred (first )?name\*?$", "preferred_name"),
    (r"^e-?mail( address)?\*?$", "email"), (r"^(phone|phone number|mobile|mobile phone)\*?$", "phone"),
    (r"^(current )?location( \(city\))?\*?$", "location"), (r"^city\*?$", "city"),
    (r"^state\*?$", "state"), (r"^(zip|zip code|postal code)\*?$", "postal_code"),
    (r"^(street address|address line 1)\*?$", "street"), (r"^country( of residence)?\*?$", "country"),
    (r"^linkedin( profile)?( url)?\*?$", "linkedin"), (r"^github( profile)?( url)?\*?$", "github"),
    (r"^(website|personal website|portfolio)( url)?\*?$", "website"),
    (r"^(school|university|college|school name|university name)\*?$", "school"),
    (r"^(major|field of study)\*?$", "major"), (r"^(cumulative )?gpa\*?$", "gpa"),
    (r"^(expected )?graduation( date)?\*?$", "graduation"),
    (r"^are you (legally )?authorized to work in (the )?(united states|us|u\.s\.)\??\*?$", "work_authorized_us"),
    (r"^will you( now or in the future)? require( visa)? sponsorship( now or in the future)?\??\*?$", "needs_sponsorship"),
    (r"^do you( now or in the future)? require( visa)? sponsorship\??\*?$", "needs_sponsorship"),
    (r"^do you have unrestricted work authorization\??\*?$", "unrestricted_authorization"),
    (r"^country of citizenship\*?$", "citizenship"),
    (r"^are you a us person\??\*?$", "us_person"),
    (r"^(gender|gender identity)\*?$", "gender"), (r"^(race|race / ethnicity|race/ethnicity)\*?$", "race"),
    (r"^veteran status\*?$", "veteran"), (r"^disability status\*?$", "disability"),
    (r"^(desired salary|salary expectations|desired compensation)\*?$", "salary"),
    (r"^notice period\*?$", "notice_period"),
]
REFUSE = re.compile(r"do not use (?:ai|artificial intelligence)|don.t use ai|without (?:ai|artificial intelligence)|graded (?:test|work|assessment)|solve this|prove that|coding challenge",re.I)


def field_key(label):
    label=" ".join(label.strip().casefold().split()).rstrip(" *?:")
    for pattern,key in RULES:
        if re.fullmatch(pattern,label): return key
    if re.search(r"(?:which|what).*(?:college|university|school).*(?:attend|enroll)|name of (?:your |the )?(?:college|university|school)",label):return 'school'
    if re.fullmatch(r"(?:current |pursuing |academic )?degree(?: type)?",label):return 'degree'
    if re.search(r'when.*(?:expect|plan).*graduat|(?:expected|anticipated).*graduation',label):return 'graduation'
    if 'highest' in label and re.search(r'education|degree',label):return 'highest_completed_degree'
    if re.search(r'(?:will|do).*(?:require|need).*sponsor|(?:require|need).*employment visa',label):return 'needs_sponsorship'
    if re.search(r'(?:authorized|eligible|authorization).*(?:united states|u\.s\.|\bus\b)',label):return 'work_authorized_us'
    if re.search(r'(?:open|willing|comfortable).*(?:in.person|on.site)',label):return 'onsite'
    return None


def category(label):
    if re.search(r"why (?:do you want|are you interested|this (?:role|company))|what interests you",label,re.I):return "motivation"
    if re.search(r"(?:tell|describe|share).{0,25}(?:project|something you (?:built|created))",label,re.I):return "project"
    if re.search(r"(?:tell us about yourself|summarize your (?:background|experience)|describe your (?:background|experience))",label,re.I):return "experience"
    return None


def _option_value(key, value, options):
    normalize=lambda v:re.sub(r"[^a-z0-9]", "", v.casefold())
    aliases={
        'degree':{'bs':{"bachelor", "bachelors", "bachelorsdegree", "bachelorofscience", "undergraduate"},
                  'ms':{"master", "masters", "mastersdegree", "masterofscience"}},
        'country':{'unitedstates':{"us", "usa", "unitedstatesofamerica","unitedstates1"}},
        'citizenship':{'unitedstates':{"us", "usa", "unitedstatesofamerica"}},
        'school':{'universityofcaliforniaberkeley':{"ucberkeley","universitycaliforniaberkeley"},'universitycaliforniaberkeley':{"ucberkeley","universityofcaliforniaberkeley"}},
        'disability':{'noidonothaveadisability':{"noidonothaveadisabilityandhavenothadoneinthepast"}},
    }
    if key=='graduation' and re.fullmatch(r'\d{4}-\d{2}',value):
        year,month=value.split('-');season='Spring' if 3<=int(month)<=5 else 'Summer' if 6<=int(month)<=8 else 'Fall' if 9<=int(month)<=11 else 'Winter'
        seasonal=[x for x in options if normalize(x)==normalize(season+' '+year)]
        if len(seasonal)==1:return seasonal[0]
    allowed={normalize(value)}|aliases.get(key,{}).get(normalize(value),set())
    if value in ('Yes','No'):
        matches=[x for x in options if normalize(x)==normalize(value)]
    else:matches=[x for x in options if normalize(x) in allowed]
    if not matches and key in {'school','major','degree'}:matches=[x for x in options if normalize(x)=='other']
    if len(matches)!=1:raise Blocked('option_mismatch')
    return matches[0]


def _resume_internship(store, label):
    if not re.search(r'(?:prior|previous|past).*(?:internship|co.op).*(?:experience)|(?:have|completed).*(?:internship|co.op)',label,re.I):return None
    doc=store.db.execute("SELECT * FROM documents WHERE kind='resume'").fetchone()
    if not doc:return None
    from .util import safe_document
    import hashlib
    from pypdf import PdfReader
    path=safe_document(store.root/'documents'/doc['filename'],store.root/'documents')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=doc['hash']:raise Blocked('document_tampered')
    try:text='\n'.join(p.extract_text() or '' for p in PdfReader(path).pages)
    except Exception:return None
    section=re.split(r'\b(?:WORK )?EXPERIENCE\b',text,flags=re.I)
    if len(section)<2:return None
    work=re.split(r'(?m)^(?:PROJECTS|EDUCATION|SKILLS|PUBLICATIONS)\s*$',section[1],maxsplit=1)[0]
    lines=work.splitlines()
    from datetime import datetime,timezone
    month=datetime.now(timezone.utc).strftime('%Y-%m')
    for i,line in enumerate(lines):
        if re.search(r'\b(?:intern|internship)\b',line,re.I):
            dates=re.findall(r'\b(0[1-9]|1[0-2])/(20\d{2})\b',' '.join(lines[max(0,i-1):i+3]))
            if dates and min(y+'-'+m for m,y in dates)<=month:
                return {'value':'Yes','provenance':{'resume_hash':doc['hash'],'resume_quote':line.strip()}}
    return None


def _discovery_answer(label, options, context):
    if not re.search(r'how (?:did|have).*hear|how did.*(?:find|learn)|where did.*(?:find|hear|learn)',label,re.I):return None
    source=context.get('source','')
    if not source or source=='user':return None
    normal=lambda x:re.sub(r'[^a-z0-9]','',x.casefold())
    preferred=['companywebsite','companycareerssite','companycareerspage'] if source.startswith(('gh:','ash:','lv:','portal:')) else ['jobboard','onlinejobboard']
    unions=[x for x in options if re.search(r'(?:/|\bor\b)\s*(?:online )?job board\s*$',x,re.I)]
    for candidate in preferred+['other']:
        matches=[x for x in options if normal(x)==candidate]
        if len(matches)==1:return {'value':matches[0],'provenance':{'job_source':source}}
    if len(unions)==1:return {'value':unions[0],'provenance':{'job_source':source}}
    return None


def _sentence_cap(field, context=None):
    pattern=r'(\d+)(?:\s*[-–]\s*(\d+))?\s+sentences?'
    limit=re.search(pattern,field['label'],re.I)
    if not limit and re.search(r'^(?:first|second|third|fourth|\d+(?:st|nd|rd|th)?) example',field['label'],re.I):
        for label in (context or {}).get('form_questions',[]):
            shared=re.search(r'each (?:bullet|example|answer).{0,180}?'+pattern,label,re.I)
            if shared:limit=shared;break
    return int(limit[2] or limit[1]) if limit else None


def _fits_writing_limits(value, field, context=None):
    if field.get('maxlength',-1)>0 and len(value)>field['maxlength']:return False
    sentence_limit=_sentence_cap(field,context)
    if sentence_limit is not None and len(re.split(r'(?<=[.!?])\s+(?=[A-Z])',value))>sentence_limit:return False
    word_limit=re.search(r'(?:at most|up to|no more than|maximum|max\.?|under|limit(?: of)?)\s*(\d+)\s+words?',field['label'],re.I)
    return not word_limit or len(value.split())<=int(word_limit[1])


def _compatible_binding(key, label):
    terms={
        'needs_sponsorship':r'sponsor|visa|immigration|h.?1b',
        'work_authorized_us':r'authoriz|work permit|legally.*work|right.*work',
        'unrestricted_authorization':r'authoriz|work permit|legally.*work|right.*work',
        'us_person':r'u\.?s\.? person|citizen|export|itar',
        'citizenship':r'citizen|nationality',
        'professional_years':r'years?.*(?:experience|professional|work)|experience.*years?',
        'onsite':r'on.?site|in.person|office|hybrid',
        'background_check':r'background.*check|screening',
        'recording':r'record|video',
        'sms':r'sms|text message',
    }
    return key not in terms or bool(re.search(terms[key],label,re.I))


def _foreign_targets(store, template, context):
    targets=re.findall(r"(?:^|[.!?]\s+)([A-Z][\w -]{1,50}?) (?:feels|especially caught|is interesting)",template['body']) if template['category']=='motivation' else []
    return [name for name in targets if store.company(name) not in store.company(context.get('company',''))]


def _approved_sentences(store, context):
    choices=[]
    for t in store.templates():
        # Identify an explicitly targeted employer in motivation samples, then omit
        # those sentences when adapting the sample for another employer.
        foreign=_foreign_targets(store,t,context)
        for i,sentence in enumerate(re.split(r'(?<=[.!?])\s+(?=[A-Z])',t['body'])):
            if any(re.search(r'\b'+re.escape(name)+r'\b',sentence,re.I) for name in foreign):continue
            choices.append({'id':t['id']+':'+str(i),'text':sentence,'template_id':t['id'],'revision':t['revision']})
    return choices


def _validate_writing(store, answer):
    templates={t['id']:t for t in store.templates()}
    parts=answer['provenance'].get('sample_parts',[])
    if not parts or answer['value']!=' '.join(p['text'] for p in parts):raise Blocked('unsupported_or_stale_sample')
    for part in parts:
        source=templates.get(part['template_id'])
        if not source or source['revision']!=part['revision'] or part['text'] not in source['body']:raise Blocked('unsupported_or_stale_sample')


def resolve(store, host, field, provider=None, context=None):
    label=field['label'];options=field.get('options',[]);context=dict(context or {})
    context['max_sentences']=_sentence_cap(field,context)
    if REFUSE.search(label):raise Blocked('human_work_sample',label)
    writing=store.writing_answer(host,label,options)
    if writing:
        try:
            _validate_writing(store,writing)
            if not _fits_writing_limits(writing['value'],field,context):raise Blocked('answer_too_long',label)
        except Blocked:
            if not provider:raise
            store.db.execute('DELETE FROM writing_answers WHERE id=?',(store.question_key(host,label,options),))
        else:
            store.resolve_known_question(host,label)
            return {'field':field,**writing}
    saved=store.saved_answer(host,label,options)
    key=None;template=None;derived=None
    if saved:
        if saved['fact_key']:
            fact=store.facts().get(saved['fact_key'])
            if not fact or fact['value']!=saved['value']:raise Blocked('stale_answer',label)
        value=saved['value'];provenance={'answer_id':saved['id'],'revision':saved['revision']}
    else:
        key=field_key(label)
        employer=host.split('|',1)[1] if '|' in host else None
        prior={store.company(x) for x in store.settings()['prior_employers']}
        if employer and employer not in prior:
            if re.search(r'(?:previously|ever|before).{0,20}(?:work|employ)|(?:work|employ).{0,30}(?:previously|before)',label,re.I):key='worked_outside_resume'
            elif re.search(r'(?:know anyone|family|spouse|partner|relative).{0,70}(?:company|work|employ)|(?:know anyone|personal contacts)',label,re.I):key='contacts_outside_resume'
        if not key and re.search(r'authorized to work.*country where this job',label,re.I) and re.search(r'United States|\bUS\b|\bUSA\b',context.get('location',''),re.I):key='work_authorized_us'
        binding=store.field_binding(host,label,options)
        if binding:
            key=binding['fact_key'] or key
            template=next((t for t in store.templates() if t['id']==binding['template_id']),None)
        cat=category(label) if field.get('type') in ('text','textarea') and not options else None
        if not template and cat:
            choices=[t for t in store.templates() if t['category']==cat]
            selected=choices[0]['id'] if len(choices)==1 else provider.choose_answer(label,choices) if choices and provider else None
            template=next((t for t in choices if t['id']==selected),None)
        if not key and not template:derived=_resume_internship(store,label) or _discovery_answer(label,options,context)
        if not key and not template and not derived and provider and field.get('required'):
            from .config import FACTS
            facts={k:{'label':FACTS[k],'value':v['value']} for k,v in store.facts().items() if k not in {'worked_outside_resume','contacts_outside_resume'}}
            if not re.search(r'summer\s*2027',context.get('title',''),re.I):facts.pop('summer_2027_relocate',None)
            matched=provider.match_field(field,facts,store.templates(),context)
            proposed_key=matched.get('fact_key');tid=matched.get('template_id')
            if bool(proposed_key) != bool(tid):
                if proposed_key in facts:
                    # These two concepts cannot be conflated even by semantic matching.
                    if _compatible_binding(proposed_key,label) and not ('highest' in label.casefold() and proposed_key=='degree'):
                        key=proposed_key;store.bind_field(host,label,options,fact_key=key)
                elif tid:
                    template=next((t for t in store.templates() if t['id']==tid),None)
                    if template:store.bind_field(host,label,options,template_id=tid)
        if template and (_foreign_targets(store,template,context) or not _fits_writing_limits(template['body'],field,context)):template=None
        is_writing=not options and field.get('type') in ('text','textarea') and (cat or re.search(r'example|describe|tell us|why|what interests|share.*(?:work|project)',label,re.I))
        if not template and not key and not derived and provider and is_writing:
            choices=_approved_sentences(store,context)
            ids=provider.choose_sentences(label,choices,context,field.get('maxlength',-1)) if choices else []
            by_id={x['id']:x for x in choices}
            if ids and len(ids)<=4 and len(ids)==len(set(ids)) and all(x in by_id for x in ids):
                parts=[{k:v for k,v in by_id[x].items() if k!='id'} for x in ids]
                writing={'value':' '.join(p['text'] for p in parts),'provenance':{'sample_parts':parts}}
                _validate_writing(store,writing)
                if not _fits_writing_limits(writing['value'],field,context):raise Blocked('answer_too_long',label)
                store.save_writing_answer(host,label,options,writing);store.resolve_known_question(host,label)
                return {'field':field,**writing}
        if template:
            value=template['body'];provenance={'template_id':template['id'],'revision':template['revision']}
        elif derived:
            value=derived['value'];provenance=derived['provenance']
        else:
            fact=store.facts().get(key)
            if not fact:
                if field.get('required'):raise Blocked('missing_fact',label)
                store.resolve_known_question(host,label)
                return None
            value=fact['value']
            if key=='gpa' and field.get('type')=='number' and '/' in value:value=value.split('/',1)[0].strip()
            provenance={'fact_key':key,'revision':fact['revision']}
    if field.get('type') in ('radio','select','combobox','checkbox') and options:
        try:value=_option_value(key,value,options)
        except Blocked:raise Blocked('option_mismatch',label)
    if field.get('maxlength',-1)>0 and len(value)>field['maxlength']:raise Blocked('answer_too_long',label)
    if field.get('type')=='number' and not re.fullmatch(r'-?\d+(?:\.\d+)?',value):raise Blocked('numeric_answer_needed',label)
    store.resolve_known_question(host,label)
    return {'field':field,'value':value,'provenance':provenance}


def validate_package(store, job, package):
    if package.get("job_id")!=job["id"] or package.get("url")!=job["url"]:
        raise Blocked("package_destination_mismatch")
    if not isinstance(package.get("answers"),list): raise Blocked("invalid_package")
    facts=store.facts()
    writing_context={"form_questions":[f["label"] for step in package.get("steps",[]) for f in step.get("fields",[])]}
    for answer in package["answers"]:
        field=answer["field"]
        prov=answer.get("provenance",{})
        if not _fits_writing_limits(answer["value"],field,writing_context):raise Blocked("answer_too_long",field["label"])
        if 'sample_parts' in prov:
            _validate_writing(store,answer)
            cached=store.writing_answer(job.get('answer_scope',job['host']),field['label'],field.get('options',[]))
            if cached!={'value':answer['value'],'provenance':prov}:raise Blocked('unsupported_or_stale_sample')
            continue
        if "template_id" in prov:
            template=next((x for x in store.templates() if x["id"]==prov["template_id"]),None)
            if not template or _foreign_targets(store,template,job) or (template["category"]!=category(field["label"]) and not ((store.field_binding(job.get("answer_scope",job["host"]),field["label"],field.get("options",[])) or {}).get("template_id")==template["id"])) or template["revision"]!=prov["revision"] or template["body"]!=answer["value"]:
                raise Blocked("unsupported_or_stale_template")
            continue
        expected=resolve(store,job.get("answer_scope",job["host"]),field,context=job)
        if expected != answer:
            raise Blocked("unsupported_or_stale_answer",field["label"])
    for doc in package.get("documents",[]):
        actual=store.db.execute("SELECT * FROM documents WHERE kind=?",(doc["kind"],)).fetchone()
        if not actual or doc["hash"]!=actual["hash"] or doc.get("filename")!=actual["filename"]:
            raise Blocked("document_changed")
    if not any(d["kind"]=="resume" for d in package.get("documents",[])):
        raise Blocked("resume_not_in_package")
    for step in package.get("steps",[]):
        for field in step.get("fields",[]):
            if not field.get("required"):continue
            entries=package["documents"] if field["type"]=="file" else package["answers"]
            if not any(x["field"]==field for x in entries):raise Blocked("required_answer_missing",field["label"])
    if package.get("facts_hash")!=digest(facts):
        raise Blocked("facts_changed")
