"""Constrained free-provider explanations. A provider never authorises a booking."""
import json
import re
import urllib.request
from .settings import advisory_settings,model_label
from .advisory import _review_strings


def choose(prompt,context,field,allowed):
    settings=advisory_settings()
    base={'provider':'local_planning_rules','provider_label':'Transparent planning rules','external_data_sent':False,'integration_status':'AI is not configured; local planning reasons shown.'}
    if not settings['enabled'] or not settings['api_key'] or not settings['base_url']: return base
    attempted=[]
    for model in [settings['model']]+settings.get('fallback_models',[]):
        if settings['provider']!='openrouter' or not model.endswith(':free'): continue
        attempted.append(model)
        body={'model':model,'temperature':0.1,'max_tokens':850,'messages':[{'role':'system','content':'You assist an ophthalmology team with administrative planning. No diagnosis, safe-wait prediction, medical clearance or autonomous urgency. Use only supplied evidence. Never use an image model confidence as disease severity or urgency. Return JSON only.'},{'role':'user','content':prompt+' Context: '+json.dumps(context)}]}
        if settings['provider']=='openrouter': body.update(response_format={'type':'json_object'},reasoning={'enabled':False},provider={'max_price':{'prompt':0,'completion':0}})
        request=urllib.request.Request(settings['base_url']+'/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+settings['api_key'],'Content-Type':'application/json'})
        base['external_data_sent']=True
        try:
            with urllib.request.urlopen(request,timeout=25) as response: payload=json.load(response)
            text=payload['choices'][0]['message']['content'].strip().strip('`').removeprefix('json').strip()
            parsed=json.loads(text)
            if parsed.get(field) not in allowed: raise ValueError('Invalid candidate')
            reasons=_review_strings(parsed.get('reason_points'))
            reasons=[x for x in reasons if not re.search(r'\b(?:safe to (?:wait|delay)|medically safe|confidence (?:justifies|means)|low (?:score|percentage).*defer)\b',x,re.I)]
            if field=='suggested_month' and any(re.search(r'\b\d{4}-\d{2}-\d{2}\b',x) for x in reasons): raise ValueError('Exact dates are reserved for admin')
            if len(reasons)<2: raise ValueError('No supported explanation')
            return {**base,field:parsed[field],'reason_points':reasons,'provider':settings['provider']+'_api','provider_label':model_label(model),'integration_status':'AI ranked supplied candidates; human approval is required.','attempted_models':attempted,'fallback_used':model!=settings['model']}
        except Exception: pass
    return {**base,'attempted_models':attempted,'integration_status':'Configured free AI endpoints are unavailable or returned unsupported content. Local planning reasons shown.'}
