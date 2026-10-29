"""Isolated Android smoke-test backend. Never uses cloud records or messaging."""
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['CATATRIAGE_DATA_DIR']=str(ROOT/'deployment/demo_app/data/.android_qa')
os.environ['CATATRIAGE_SESSION_SECRET']='isolated-android-qa-session-secret-only'
os.environ.pop('CATATRIAGE_DATABASE_URL',None)
os.environ.pop('CATATRIAGE_HOSTED',None)
from deployment.demo_app import main
for key in ('CATATRIAGE_DATABASE_URL','FIREBASE_WEB_API_KEY','FIREBASE_MAIL_CONFIG_FILE','GMAIL_APP_PASSWORD','GMAIL_APP_PASSWORD_FILE','GMAIL_OAUTH_JSON','GMAIL_OAUTH_JSON_FILE','WHATSAPP_ENABLE','OPENROUTER_API_KEY','OPENROUTER_API_KEY_FILE','DASHSCOPE_API_KEY'):
    os.environ.pop(key,None)
os.environ['AI_ENABLE']='false'
os.environ['QWEN_ENABLE']='false'

if __name__=='__main__':
    import uvicorn
    uvicorn.run(main.app,host='127.0.0.1',port=8002,access_log=False)
