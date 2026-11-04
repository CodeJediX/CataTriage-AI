from deployment.demo_app import judge_access
from test_demo import client


def test_competition_credentials_are_disclosed_only_after_unlock(client, monkeypatch):
    key = "test-key-for-competition-access-only"
    monkeypatch.setenv("CATATRIAGE_JUDGE_KEY", key)
    accounts = judge_access.accounts(key)

    login_page = client.get("/login/judges")
    assert login_page.url.path == "/login"
    assert "Competition judge access" in login_page.text
    assert all(account["password"] not in login_page.text for account in accounts)

    csrf = client.cookies["catatriage_csrf"]
    code = judge_access.access_code(key)
    missing_csrf = client.post("/login/judges", data={"access_code": code, "csrf": ""})
    assert missing_csrf.status_code == 403
    wrong_code = client.post("/login/judges", data={"access_code": "incorrect", "csrf": csrf})
    assert wrong_code.status_code == 403
    assert all(account["password"] not in wrong_code.text for account in accounts)

    unlocked = client.post("/login/judges", data={"access_code": code, "csrf": csrf})
    assert unlocked.url.path == "/login"
    assert all(account["password"] in unlocked.text for account in accounts)
    assert key not in unlocked.text and code not in unlocked.text
    assert client.get("/admin", follow_redirects=False).status_code == 303

    signed_out = client.post("/logout", data={"csrf": csrf})
    assert all(account["password"] not in signed_out.text for account in accounts)


def test_disclosure_cookie_is_expired_and_invalid_after_key_rotation(monkeypatch):
    key = "test-key-for-competition-access-only"
    now = 1_000_000
    monkeypatch.setattr(judge_access.time, "time", lambda: now)
    token = judge_access.disclosure_token(key)
    assert judge_access.can_view(key, token)
    assert not judge_access.can_view(key + "-rotated", token)
    assert not judge_access.can_view(key, token[:-1] + "☃")
    now += judge_access.ACCESS_SECONDS
    assert not judge_access.can_view(key, token)
