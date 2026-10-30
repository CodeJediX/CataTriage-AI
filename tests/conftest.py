"""Tests never use live mail credentials from the developer's local config."""
import pytest


@pytest.fixture(autouse=True)
def isolate_mail_credentials(monkeypatch):
    for key in ('CATATRIAGE_DATABASE_URL','CATATRIAGE_HOSTED','FIREBASE_WEB_API_KEY','FIREBASE_MAIL_CONFIG_FILE','GMAIL_APP_PASSWORD','GMAIL_APP_PASSWORD_FILE','GMAIL_OAUTH_JSON','GMAIL_OAUTH_JSON_FILE','WHATSAPP_ENABLE'):
        monkeypatch.delenv(key,raising=False)
