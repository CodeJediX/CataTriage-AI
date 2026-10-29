$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
$env:ANDROID_HOME=Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$env:GRADLE_USER_HOME=Join-Path $projectRoot '.build-cache\gradle'
$env:TEMP=Join-Path $projectRoot '.build-cache\tmp'
$env:TMP=$env:TEMP
New-Item $env:GRADLE_USER_HOME,$env:TEMP -ItemType Directory -Force | Out-Null
& (Join-Path $projectRoot '.venv\Scripts\python.exe') tools/prepare_android_signing.py
if($LASTEXITCODE -ne 0){throw 'Signing key preparation failed.'}
$env:CATATRIAGE_ANDROID_SIGNING=Join-Path $projectRoot 'deployment\demo_app\data\.secrets\android_signing\signing.properties'
$cachedGradle=Get-ChildItem (Join-Path $env:USERPROFILE '.gradle\wrapper\dists\gradle-8.11.1-bin') -Recurse -Filter gradle.bat | Select-Object -First 1 -ExpandProperty FullName
if($cachedGradle){& $cachedGradle -p android assembleRelease lintRelease}else{& .\android\gradlew.bat -p android assembleRelease lintRelease}
if($LASTEXITCODE -ne 0){throw 'Android build or lint failed.'}
$destination=Join-Path $projectRoot 'output\android'
New-Item $destination -ItemType Directory -Force | Out-Null
Copy-Item 'android/app/build/outputs/apk/release/app-release.apk' (Join-Path $destination 'CataTriage-Doctor-1.1.0.apk') -Force
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -c "import hashlib,json;from pathlib import Path;p=Path('output/android/CataTriage-Doctor-1.1.0.apk');Path('output/android/release.json').write_text(json.dumps({'version':'1.1.0','filename':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size,'minimum_android':'8.0','package':'com.catatriage.doctor'},indent=2))"
Write-Output 'Release APK and checksum are in output/android.'
