from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .config import FACTS, validate_fact
from .util import private_dir


def import_resume(store,path:Path,kind='resume'):
    if kind not in ('resume','transcript'):raise ValueError('Unsupported document kind')
    if path.is_symlink() or not path.is_file():raise ValueError('Choose a regular PDF')
    if path.stat().st_size>20*1024*1024:raise ValueError('PDF exceeds 20 MiB')
    data=path.read_bytes()
    if not data.startswith(b'%PDF-'):raise ValueError('Not a PDF')
    from pypdf import PdfReader
    reader=PdfReader(path)
    if reader.is_encrypted or len(reader.pages)>50:raise ValueError('Encrypted or excessive PDF')
    text='\n'.join(p.extract_text() or '' for p in reader.pages)
    if kind=='resume' and not text.strip():raise ValueError('Resume needs selectable text; supply an accessible text PDF')
    h=hashlib.sha256(data).hexdigest();dest=private_dir(store.root/'documents')/(h+'.pdf')
    fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600) if not dest.exists() else None
    if fd is not None:
        with os.fdopen(fd,'wb') as f:f.write(data)
    store.db.execute('INSERT INTO documents VALUES(?,?,?) ON CONFLICT(kind) DO UPDATE SET hash=excluded.hash,filename=excluded.filename',(kind,h,dest.name))
    store.event('document_imported',kind,{'hash':h})
    candidates={}
    if kind=='resume':
        lines=[l.strip() for l in text.splitlines() if l.strip()]
        if lines and re.fullmatch(r'[A-Za-z][A-Za-z .\'-]{2,100}',lines[0]):
            candidates['full_name']=lines[0];parts=lines[0].split()
            if len(parts)==2:candidates.update(first_name=parts[0],last_name=parts[1])
        email=re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',text)
        if email:candidates['email']=email[0]
        phone=re.search(r'\(?\d{3}\)?[ .-]+\d{3}[ .-]+\d{4}',text)
        if phone:candidates['phone']=phone[0]
        loc=re.search(r'^([A-Za-z .]+, [A-Z]{2})\s*[•|]',text,re.M)
        if loc:candidates['location']=loc[1]
        gpa=re.search(r'GPA:\s*([0-9.]+\s*/\s*[0-9.]+)',text)
        if gpa:candidates['gpa']=gpa[1]
        grad=re.search(r'GPA:[^\n]*?\b(0[1-9]|1[0-2])/(20\d{2})\b',text)
        if grad:candidates['graduation']=grad[2]+'-'+grad[1]
        website=re.search(r'\b(?:https?://)?[\w.-]+\.(?:com|dev|io)\b',lines[1] if len(lines)>1 else '')
        if website and not (email and website[0] in email[0]):candidates['website']='https://'+website[0].removeprefix('https://').removeprefix('http://')
        school=re.search(r'^(University[^•\n]+)\s*•\s*GPA:',text,re.M)
        if school:candidates['school']=school[1].strip()
        degree=re.search(r'^(B\.S\.)\s*\|\s*([^\n]+)',text,re.M)
        if degree:candidates['degree']=degree[1];candidates['major']=degree[2].strip()
        if 'SKILLS' in text:
            section=text.split('SKILLS',1)[1]
            skills=[]
            for line in section.splitlines():
                if ':' in line:skills.extend(x.strip() for x in line.split(':',1)[1].split(',') if x.strip())
            if skills:candidates['skills']=', '.join(skills)
        # Candidate facts require a single confirmation pass; parsing never approves legal status.
        store.put_facts(candidates,source='resume:'+h,confirmed=False)
        private_dir(store.root/'config')
        p=store.root/'config'/'resume.txt'
        if p.is_symlink():raise ValueError('Unsafe resume text destination')
        p.write_text(text);os.chmod(p,0o600)
    return {'hash':h,'candidates':candidates,'text':text}


def model_candidates(store,provider):
    path=store.root/'config'/'resume.txt'
    if not path.is_file():raise ValueError('Import a resume first')
    text=path.read_text();result=provider.extract_resume(text);values={}
    forbidden={'work_authorized_us','needs_sponsorship','citizenship','us_person','unrestricted_authorization','race','gender','veteran','disability','professional_years','earliest_start','latest_start'}
    for f in result.get('facts',[]):
        key,value,quote=f.get('key'),f.get('value'),f.get('quote')
        if key not in FACTS or key in forbidden or not isinstance(quote,str) or not quote.strip() or quote not in text:continue
        if not isinstance(value,str) or value not in quote:continue
        try:values[key]=validate_fact(key,value)
        except ValueError:continue
    store.put_facts(values,source='resume:model-proposal',confirmed=False)
    return values
