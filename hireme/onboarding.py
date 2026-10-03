from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import tempfile
from pathlib import Path

from .config import FACTS, validate_fact
from .util import private_dir,write_private_blob

MAX_PDF_BYTES=20*1024*1024


def _read_pdf_bytes(path):
    if path.is_symlink() or not path.is_file():raise ValueError('Choose a regular PDF')
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):raise ValueError('Choose a regular PDF')
            data=source.read(MAX_PDF_BYTES+1)
    except OSError:raise ValueError('Choose a readable regular PDF') from None
    if len(data)>MAX_PDF_BYTES:raise ValueError('PDF exceeds 20 MiB')
    return data


def _store_imported_pdf(path,data):
    """An explicit import can restore the bytes belonging to a hash-named PDF."""
    if path.name!=hashlib.sha256(data).hexdigest()+'.pdf' or path.is_symlink():raise ValueError('Unsafe imported PDF destination')
    if not path.exists():
        write_private_blob(path,data);return False
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as existing:
            if not stat.S_ISREG(os.fstat(existing.fileno()).st_mode):raise ValueError('Unsafe imported PDF destination')
            if existing.read(MAX_PDF_BYTES+1)==data:return False
    except PermissionError:
        if path.is_symlink() or not path.is_file():raise ValueError('Unsafe imported PDF destination') from None
    except OSError:raise ValueError('Stored PDF could not be checked') from None
    # Valid hash-addressed content is never changed. The incoming bytes hash to
    # this filename, so replacement repairs a corrupt artifact, including history.
    fd,temporary=tempfile.mkstemp(dir=path.parent,prefix='.pdf-repair-')
    try:
        with os.fdopen(fd,'wb') as repaired:
            repaired.write(data);repaired.flush();os.fsync(repaired.fileno())
        if path.is_symlink():raise ValueError('Unsafe imported PDF destination')
        os.replace(temporary,path)
        directory_fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory_fd)
        finally:os.close(directory_fd)
    finally:Path(temporary).unlink(missing_ok=True)
    return True


def import_resume(store,path:Path,kind='resume'):
    if kind not in ('resume','transcript'):raise ValueError('Unsupported document kind')
    data=_read_pdf_bytes(path)
    if not data.startswith(b'%PDF-'):raise ValueError('Not a PDF')
    from pypdf import PdfReader
    reader=PdfReader(io.BytesIO(data))
    if reader.is_encrypted or len(reader.pages)>50:raise ValueError('Encrypted or excessive PDF')
    parts=[];length=0
    for page in reader.pages:
        part=page.extract_text() or '';length+=len(part)
        if length>100000:raise ValueError('PDF text exceeds 100,000 characters')
        parts.append(part)
    text='\n'.join(parts)
    if kind=='resume' and not text.strip():raise ValueError('Resume needs selectable text; supply an accessible text PDF')
    h=hashlib.sha256(data).hexdigest()
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
        private_dir(store.root/'config')
        p=store.root/'config'/'resume.txt'
        if p.is_symlink():raise ValueError('Unsafe resume text destination')
    with store.transaction():
        known=store.facts(False)
        proposals={key:validate_fact(key,value) for key,value in candidates.items()}
        proposals={key:value for key,value in proposals.items()
                   if not (known.get(key,{}).get('confirmed') and known[key]['value']==value)}
        # Exact existing confirmations remain authoritative. New/changed values
        # require review; identity rejection precedes selecting the new PDF.
        if proposals:store.put_facts(proposals,source='resume:'+h,confirmed=False)
        dest=private_dir(store.root/'documents')/(h+'.pdf')
        repaired=_store_imported_pdf(dest,data)
        previous=store.db.execute('SELECT hash FROM documents WHERE kind=?',(kind,)).fetchone()
        if previous and previous['hash']!=h:
            from .document_controls import invalidate_document_drafts
            invalidate_document_drafts(store,kind)
        store.db.execute('INSERT INTO documents VALUES(?,?,?) ON CONFLICT(kind) DO UPDATE SET hash=excluded.hash,filename=excluded.filename',(kind,h,dest.name))
        store.event('document_imported',kind,{'hash':h})
        if repaired:store.event('document_repaired',kind,{'hash':h})
    if proposals:store.export_config()
    if kind=='resume':
        p.write_text(text);os.chmod(p,0o600)
    return {'hash':h,'candidates':candidates,'text':text,'repaired':repaired}


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
