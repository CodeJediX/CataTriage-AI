"""Built-in navigation chat. No patient lookup, clinical inference or external API."""
import json
import re
from pathlib import Path

COMMON = {
    'calendar': ('Calendar', '/calendar?kind=surgery', ('calendar','appointment','appointments','schedule')),
    'pending': ('Pending surgery dates', '/surgery/pending', ('pending','bell','waiting','unconfirmed')),
    'models': ('Model evidence', '/model', ('model','models','accuracy','training','test','graphs','evidence')),
    'workflow': ('Four-agent workflow', '/about', ('agent','agents','workflow','safety','how it works')),
    'patients': ('Patient registry', '/cases', ('patient','patients','registry','reports','report')),
}
ROLE_LINKS = {
    'doctor': {
        'home': ('Doctor workspace', '/doctor', ('home','dashboard','workspace')),
        'profile': ('My profile & security', '/doctor/profile', ('profile','photo','photograph','username','password','account')),
        'inbox': ('Inbox & sent', '/doctor/inbox', ('inbox','message','messages','chat','sent')),
        'upload': ('Capture both eyes', '/cases/new', ('upload','capture','image','images','left','right')),
        'leave': ('Leave requests', '/doctor/leave', ('leave','holiday')),
    },
    'admin': {
        'home': ('Hospital dashboard', '/admin', ('home','dashboard','workspace','capacity','beds')),
        'accounts': ('Manage accounts', '/admin/accounts', ('account','accounts','register','doctor','doctors','edit','delete')),
        'inbox': ('Inbox & announcements', '/admin/messages', ('inbox','message','messages','chat','sent','announcement')),
        'months': ('Approved surgery months', '/admin/surgery', ('month','months','date','dates','booking','surgery')),
    },
    'technician': {
        'home': ('Capture & support', '/support', ('home','dashboard','workspace','support')),
        'upload': ('New patient intake', '/cases/new', ('upload','capture','image','images','register','intake','left','right')),
    },
}


def links_for(role): return {**COMMON, **ROLE_LINKS.get(role, {})}


def menu(role):
    links = links_for(role)
    return {'mode':'Built-in workspace guide','role':role,'links':[{'key':key,'label':value[0],'href':value[1]} for key,value in links.items()], 'quick_prompts':['Open my workspace','Open calendar','Pending surgery dates','Explain the four agents','Month and date workflow','Show model accuracy','Image capture checklist']}


def answer(role, text):
    query = re.sub(r'\s+', ' ', text.lower()).strip()
    catalog = links_for(role)
    def result(message, keys=()):
        return {'message':message,'links':[{'label':catalog[k][0],'href':catalog[k][1]} for k in keys if k in catalog], 'mode':'Built-in workspace guide','external_data_sent':False}
    if re.search(r'\b(diagnos\w*|treat\w*|medicine|medication|prescri\w*|safe to wait|do i have|am i sick)\b', query):
        return result('I can help with workspace navigation and explain how the system works. A doctor must interpret patient findings and decide care. Open the patient record for clinical review.', ('patients','workflow'))
    if any(word in query for word in ('four agent','4 agent','the agents','agent workflow')):
        return result('The four stages work in order:\n1. Preprocessing checks completeness and image quality.\n2. Model inference runs the relevant research model.\n3. Safety validation flags uncertain or unsupported results.\n4. Explanation and reporting presents the evidence for doctor review.\nThe agents do not approve surgery or set a clinical tier.', ('workflow','models'))
    if any(word in query for word in ('month and date','month vs','month workflow','date workflow','why this month','surgery workflow')):
        return result('The AI proposes a month with reasons from the recorded assessment. The doctor reviews and approves that month. The admin then checks the calendar and confirms an exact date and time within it. The red bell remains while a date is pending. Changed clinical evidence requires fresh doctor approval.', ('pending','calendar','months') if role=='admin' else ('patients','pending','calendar'))
    if any(word in query for word in ('pending','red bell','unconfirmed')):
        return result('The pending list contains doctor-approved months awaiting an exact surgery date. Opening the list does not clear the red bell. The admin confirms the final date and time within the approved month.', ('pending','calendar'))
    if any(word in query for word in ('tier','priority')):
        return result('Tier 1, Tier 2 and Tier 3 are doctor-entered workflow priorities, from higher priority to routine planning. They are not diagnoses or guaranteed safe waiting periods. Model confidence does not select a tier. Review the recorded doctor reason in the patient record.', ('patients','pending'))
    if any(word in query for word in ('checklist','quality','blurry','unknown eye')):
        return result('Capture checklist:\n• Choose the correct patient and image modality.\n• Upload left and right images to their own fields. If the side is unknown, use “Eye side unknown”.\n• Use an original, focused image with suitable lighting.\n• Review the immediate quality feedback.\n• Record symptoms and notes before doctor review.\nAn empty upload field does not add a default image.', ('upload','patients'))
    if any(word in query for word in ('accuracy','training result','test result','model score')):
        root=Path(__file__).resolve().parents[2]; lines=[]
        for label,folder in (('Multi-data grading','cataract_grade_multidata_real'),('Image-context fusion','clinical_fusion_catscreen_real')):
            data=json.loads((root/'models'/folder/'metrics.json').read_text(encoding='utf-8'))
            metrics=data['metrics'];lines.append(f"{label}: training {metrics['train']['accuracy']:.1%}; validation {metrics['validation']['accuracy']:.1%}; test {metrics['test']['accuracy']:.1%}.")
        return result('\n'.join(lines)+'\nThese are research measurements on the listed datasets. High training accuracy alone can reflect memorisation; test results and per-class errors matter too.', ('models',))
    if any(word in query for word in ('tour','get started','what can you','help','options')) or query in {'hi','hello','hey'}:
        return result('I can open the right workspace page, explain the four agents, show current model accuracy, explain month-to-date scheduling, or give an image capture checklist. Choose a shortcut or type “open calendar”. I do not change records or make medical decisions.', ('home','patients','calendar','pending'))
    ranked=[]
    for key,(_,_,words) in catalog.items():
        hits=sum(bool(re.search(r'\b'+re.escape(word)+r'\b',query)) for word in words)
        if hits:ranked.append((hits,key))
    ranked.sort(key=lambda item:-item[0])
    if ranked:
        keys=[item[1] for item in ranked[:3]]
        return result('Here are the pages available for your role. Choose a link to continue.',keys)
    return result('Try “open calendar”, “pending surgery dates”, “explain the four agents”, “show model accuracy” or “image capture checklist”. I can guide you through the workspace.', ('home','calendar','patients'))
