# CataTriage Doctor for Android

Native Java Android application, with its own touch interface and bottom navigation. This is not a WebView wrapper. Requires Android 8.0 or newer and an internet connection. Release API origin: https://catatriage-ai.vercel.app.

Features: doctor login and secure password change; assigned-patient search; contact, medical history and self-assessments; left/right/unknown original photo selection and full-resolution camera capture; image analysis and four-agent trace; reported symptoms and clinical notes; manual priority review; clinical advice and surgery-date suggestions; explicit surgery confirmation and WhatsApp handoff; calendar and device calendar reminders; Inbox/Sent, patient communication history, doctor directory, leave requests; native patient report PDF export.

Session cookies are encrypted using a device-bound Android Keystore key. Passwords and patient records are not saved to device storage by the app. The camera's temporary files remain in the app-private cache; exported reports are saved only at the location selected by the doctor. Cleartext HTTP and backups/transfers are disabled in the release. No provider API keys, server session secrets or built-in account passwords are shipped.

Research inference runs on the existing server, using the same real-data checkpoints as the website. The app does not contain an on-device model, offline inference or independent clinical validation. Priority and surgery decisions require a doctor. Manual WhatsApp opens the message in WhatsApp for the doctor to send; automatic WhatsApp still requires the verified Business sender configured in the server. New doctor setup uses the existing Firebase email flow.

## Build

JDK 17 or newer, Android SDK 35, Gradle 8.11.1 and Android Gradle Plugin 8.7.3. On this Windows workspace run `powershell -File tools/build_android.ps1` from the project root. The script uses Android Studio's JBR 21 and the installed SDK. Output: `output/android/CataTriage-Doctor-1.0.0.apk` and `release.json`.

The dedicated release signing key and passwords are kept outside this source tree at `deployment/demo_app/data/.secrets/android_signing/`. Keep a private backup of both files. Future updates must use the same signing key and increase versionCode. Never publish that folder.

`assembleQa assembleQaAndroidTest` builds a separate `.qa` package against the isolated backend `tools/serve_android_qa.py` at `10.0.2.2:8002`. This is a test-only cleartext variant, using fictional local accounts and records. Do not distribute the QA APK. Instrumentation uses the Android SDK's test runner. All mutations in API tests use isolated databases.

## Install

Copy the release APK to the Android phone, open it and grant installation permission to the app used to open the file if Android asks. Sign in with the same active doctor account used on the website. There is no APK-specific password. This is a directly installable signed APK; it has not been published to Google Play.
