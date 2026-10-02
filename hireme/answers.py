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
    label=" ".join(label.strip().casefold().split())
    for pattern,key in RULES:
        if re.fullmatch(pattern,label): return key
    return None


def category(label):
    if re.search(r"why (?:do you want|are you interested|this (?:role|company))|what interests you",label,re.I):return "motivation"
    if re.search(r"(?:tell|describe|share).{0,25}(?:project|something you (?:built|created))",label,re.I):return "project"
    if re.search(r"(?:tell us about yourself|summarize your (?:background|experience))",label,re.I):return "experience"
    return None


def resolve(store, host, field, provider=None):
    label=field["label"]
    if REFUSE.search(label):
        raise Blocked("human_work_sample",label)
    options=field.get("options",[])
    saved=store.saved_answer(host,label,options)
    if saved:
        if saved["fact_key"]:
            fact=store.facts().get(saved["fact_key"])
            if not fact or fact["value"]!=saved["value"]:
                raise Blocked("stale_answer",label)
        value=saved["value"]
        provenance={"answer_id":saved["id"],"revision":saved["revision"]}
    else:
        cat=category(label) if field.get("type") in ("text","textarea") and not options else None
        if cat:
            choices=[x for x in store.templates() if x["category"]==cat]
            selected=choices[0]["id"] if len(choices)==1 else provider.choose_answer(label,choices) if choices and provider else None
            template=next((x for x in choices if x["id"]==selected),None)
            if template:
                if field.get("maxlength",-1)>0 and len(template["body"])>field["maxlength"]:raise Blocked("answer_too_long",label)
                return {"field":field,"value":template["body"],"provenance":{"template_id":template["id"],"revision":template["revision"]}}
        key=field_key(label)
        employer=host.split("|",1)[1] if "|" in host else None
        prior={store.company(x) for x in store.settings()["prior_employers"]}
        if employer and employer not in prior:
            if re.search(r"(?:previously|ever|before).{0,20}(?:work|employ)|(?:work|employ).{0,30}(?:previously|before)",label,re.I):key="worked_outside_resume"
            elif re.search(r"(?:know anyone|family|spouse|partner|relative).{0,70}(?:company|work|employ)|(?:know anyone|personal contacts)",label,re.I):key="contacts_outside_resume"
        fact=store.facts().get(key)
        if not fact:
            if field.get("required"): raise Blocked("missing_fact",label)
            return None
        value=fact["value"]
        # Exact numerical component is an explicit formatting transform, not a changed GPA.
        if key=="gpa" and field.get("type")=="number" and "/" in value:value=value.split("/",1)[0].strip()
        provenance={"fact_key":key,"revision":fact["revision"]}
    if field.get("type") in ("radio","select","combobox","checkbox") and options:
        # Normalize presentation only; do not infer option semantics.
        matches=[x for x in options if x.strip().casefold()==value.strip().casefold()]
        if len(matches)!=1:
            raise Blocked("option_mismatch",label)
        value=matches[0]
    if field.get("maxlength",-1)>0 and len(value)>field["maxlength"]:
        raise Blocked("answer_too_long",label)
    if field.get("type")=="number" and not re.fullmatch(r"-?\d+(?:\.\d+)?",value):
        raise Blocked("numeric_answer_needed",label)
    return {"field":field,"value":value,"provenance":provenance}


def validate_package(store, job, package):
    if package.get("job_id")!=job["id"] or package.get("url")!=job["url"]:
        raise Blocked("package_destination_mismatch")
    if not isinstance(package.get("answers"),list): raise Blocked("invalid_package")
    facts=store.facts()
    for answer in package["answers"]:
        field=answer["field"]
        prov=answer.get("provenance",{})
        if "template_id" in prov:
            template=next((x for x in store.templates() if x["id"]==prov["template_id"]),None)
            if not template or template["category"]!=category(field["label"]) or template["revision"]!=prov["revision"] or template["body"]!=answer["value"]:
                raise Blocked("unsupported_or_stale_template")
            continue
        expected=resolve(store,job.get("answer_scope",job["host"]),field)
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
