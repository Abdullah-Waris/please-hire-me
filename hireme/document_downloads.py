"""Read-only downloads of the exact PDF referenced by an application record."""
from __future__ import annotations

import hashlib
import json
import re

from .onboarding import _read_pdf_bytes

NAMES = {'resume': 'resume.pdf', 'transcript': 'transcript.pdf', 'cover_letter': 'cover-letter.pdf'}


def recorded_pdf(store, application_id, index, expected_hash):
    if type(index) is not int or index < 0:
        raise ValueError('Choose a recorded PDF')
    if not isinstance(expected_hash,str) or not re.fullmatch(r'[a-f0-9]{64}',expected_hash):
        raise ValueError('Choose a recorded PDF with a valid content reference')
    record=store.application_record(application_id)
    if not record: raise ValueError('Application record not found')
    try:
        package=json.loads(record['package'])
        documents=package.get('documents',[])
        if not isinstance(documents,list) or index>=len(documents): raise ValueError
        document=documents[index]
        if not isinstance(document,dict): raise ValueError
    except (ValueError,TypeError,AttributeError):
        raise ValueError('Recorded document details could not be read') from None
    kind=document.get('kind'); filename=document.get('filename')
    if not isinstance(kind,str) or kind not in NAMES:
        raise ValueError('This recorded document is not a supported PDF')
    if document.get('hash')!=expected_hash or filename!=expected_hash+'.pdf':
        raise ValueError('The recorded document changed. Reload its evidence before downloading.')
    parent=store.root/'documents'
    if parent.is_symlink(): raise ValueError('Recorded PDF storage is unavailable')
    try: data=_read_pdf_bytes(parent/filename)
    except ValueError:
        raise ValueError('The recorded PDF cannot be read. Restore the original file from a private history backup.') from None
    if not data.startswith(b'%PDF-') or hashlib.sha256(data).hexdigest()!=expected_hash:
        raise ValueError('The recorded PDF is missing or changed. Restore the original file from a private history backup.')
    return data,NAMES[kind]
