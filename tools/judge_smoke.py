"""Run the packaged app with fresh fictional data and no external integrations."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    for key in list(os.environ):
        if key.startswith(('CATATRIAGE_','OPENROUTER_','DASHSCOPE_','GMAIL_','WHATSAPP_','FIREBASE_','GOOGLE_')):
            os.environ.pop(key,None)
    os.environ['AI_ENABLE']='false';os.environ['QWEN_ENABLE']='false';os.environ['CUDA_VISIBLE_DEVICES']='-1'
    os.environ['CATATRIAGE_SESSION_SECRET']='isolated-local-judge-smoke-session-secret'
    with tempfile.TemporaryDirectory(prefix='catatriage_judge_') as directory:
        os.environ['CATATRIAGE_DATA_DIR']=directory
        from fastapi.testclient import TestClient
        from deployment.demo_app.main import app
        from deployment.demo_app.real_models import RealModelProvider
        with TestClient(app) as client:
            assert client.get('/health').status_code==200
            for user,password,home in [('dr.maya','demo-doctor','/doctor'),('admin.nila','demo-admin','/admin'),('tech.alex','demo-tech','/support')]:
                client.get('/login');csrf=client.cookies['catatriage_csrf']
                result=client.post('/login',data={'username':user,'password':password,'csrf':csrf,'next_path':home})
                assert result.status_code==200 and str(result.url).endswith(home)
                for path in (home,'/calendar','/surgery/pending','/model','/about'):
                    assert client.get(path).status_code==200,path
                menu=client.get('/api/assistant/menu');assert menu.status_code==200
                reply=client.post('/api/assistant/chat',data={'csrf':csrf,'message':'Open calendar'})
                assert reply.status_code==200 and not reply.json()['external_data_sent']
                assert client.post('/api/assistant/chat',data={'csrf':'wrong','message':'Open calendar'}).status_code==403
            provider=RealModelProvider();provider.load_tabular();provider.load_fusion()
            assert provider._tabular_saved['model_id'].endswith('_v2')
            assert provider._fusion_saved['model_id'].endswith('_v2')
        print(json.dumps({'fresh_local_start':'passed','roles':3,'navigation_chat':'passed','csrf':'passed','both_model_checkpoints':'loaded','external_services_required':False,'raw_training_data_required':False,'live_records_changed':0}))


if __name__=='__main__':main()
