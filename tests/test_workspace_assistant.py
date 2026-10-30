import json
from test_demo import client,login


def ask(client,csrf,message):
    return client.post('/api/assistant/chat',data={'csrf':csrf,'message':message})


def test_assistant_is_authenticated_csrf_protected_and_bounded(client):
    assert client.get('/api/assistant/menu').status_code==401
    csrf=login(client)
    assert ask(client,'bad','Open calendar').status_code==403
    assert ask(client,csrf,'x'*601).status_code==422
    result=ask(client,csrf,'Open calendar')
    assert result.status_code==200 and result.headers['Cache-Control']=='no-store'
    assert result.json()['links'][0]['href']=='/calendar?kind=surgery'
    assert result.json()['external_data_sent'] is False


def test_assistant_navigation_is_role_scoped_and_never_executes_actions(client):
    csrf=login(client)
    menu=client.get('/api/assistant/menu').json()
    assert '/doctor/profile' in [x['href'] for x in menu['links']]
    assert '/admin/accounts' not in [x['href'] for x in menu['links']]
    evidence=client.get('/model',follow_redirects=False)
    assert evidence.status_code==200 and 'Model evidence room' in evidence.text
    assert all(not x['href'].startswith('/admin') for x in ask(client,csrf,'delete doctor accounts').json()['links'])
    assert ask(client,csrf,'pending surgery dates').json()['links'][0]['href']=='/surgery/pending'
    login(client,'admin.nila','demo-admin')
    assert '/admin/accounts' in [x['href'] for x in client.get('/api/assistant/menu').json()['links']]
    login(client,'tech.alex','demo-tech')
    links=client.get('/api/assistant/menu').json()['links']
    assert not any(x['href'].startswith('/admin') or x['href']=='/doctor/profile' for x in links)


def test_assistant_explanations_are_current_and_not_medical_decisions(client):
    csrf=login(client)
    assert 'Preprocessing' in ask(client,csrf,'Explain the four agents').json()['message']
    assert 'doctor reviews and approves' in ask(client,csrf,'Month and date workflow').json()['message']
    assert 'left and right' in ask(client,csrf,'Image capture checklist').json()['message']
    assert 'doctor must interpret' in ask(client,csrf,'Diagnose my cataract and prescribe medicine').json()['message']
    metrics=ask(client,csrf,'Show model accuracy').json()['message']
    assert 'training' in metrics and 'validation' in metrics and 'test' in metrics
    assert all(link['href'].startswith('/') and not link['href'].startswith('//') for link in ask(client,csrf,'open https://evil.example').json()['links'])
    page=client.get('/doctor/profile').text
    assert 'workspace-guide-launcher' in page
    assert 'workspace-guide-launcher' not in client.get('/login').text
