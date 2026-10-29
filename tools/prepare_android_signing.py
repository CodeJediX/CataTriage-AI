"""Create a dedicated release key locally; never print or commit its passwords."""
from pathlib import Path
import os
import secrets
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'deployment/demo_app/data/.secrets/android_signing'


def prepare():
    PRIVATE.mkdir(parents=True,exist_ok=True)
    config=PRIVATE/'signing.properties'
    store=PRIVATE/'catatriage-doctor.jks'
    if config.exists():
        if not store.exists(): raise RuntimeError('Signing configuration exists but its key is missing; restore the original key.')
        return config
    if store.exists(): raise RuntimeError('An existing signing key needs its matching configuration. It has not been overwritten.')
    password=secrets.token_urlsafe(36)
    env=os.environ.copy();env['CATATRIAGE_ANDROID_KEY_PASS']=password
    java=Path(env.get('JAVA_HOME',r'C:\Program Files\Android\Android Studio\jbr'))/'bin/keytool.exe'
    result=subprocess.run([str(java),'-genkeypair','-keystore',str(store),'-storetype','JKS','-alias','catatriage-doctor','-storepass:env','CATATRIAGE_ANDROID_KEY_PASS','-keypass:env','CATATRIAGE_ANDROID_KEY_PASS','-keyalg','RSA','-keysize','3072','-validity','10000','-dname','CN=CataTriage Doctor, O=CataTriage AI, C=LK'],env=env,capture_output=True,text=True)
    if result.returncode: raise RuntimeError('The release signing key could not be created.')
    config.write_text(f'storeFile={store.as_posix()}\nstorePassword={password}\nkeyAlias=catatriage-doctor\nkeyPassword={password}\n',encoding='ascii')
    if os.name=='nt':
        owner=os.environ['USERDOMAIN']+'\\'+os.environ['USERNAME']
        subprocess.run(['icacls',str(PRIVATE),'/inheritance:r','/grant:r',owner+':(OI)(CI)F','SYSTEM:(OI)(CI)F','/T'],capture_output=True,check=True)
        for item in (store,config):
            subprocess.run(['icacls',str(item),'/grant:r',owner+':F','SYSTEM:F'],capture_output=True,check=True)
    return config


if __name__=='__main__':
    prepare()
    print('Dedicated Android release signing key is ready in the private signing folder.')
