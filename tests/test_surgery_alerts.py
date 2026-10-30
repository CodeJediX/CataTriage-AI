from test_demo import client, login
from test_profile_month_planning import month_draft, approve
from deployment.demo_app import main, month_planning, planning_ai


def approved_pending(client, monkeypatch):
    monkeypatch.setattr(planning_ai, 'choose', lambda *args: {'provider': 'local_planning_rules', 'provider_label': 'Local planning checks', 'external_data_sent': False})
    csrf = login(client)
    draft = month_draft(client, csrf)
    assert approve(client, csrf, draft).status_code == 200
    return csrf, draft


def test_pending_bell_survives_reads_and_clears_only_after_admin_booking(client, monkeypatch):
    csrf, draft = approved_pending(client, monkeypatch)
    summary = client.get('/api/surgery/pending')
    assert summary.json() == {'count': 1, 'href': '/surgery/pending'}
    assert summary.headers['cache-control'] == 'no-store'
    assert 'DEMO-0001' not in summary.text  # Only a count is sent during polling.
    for path in ('/doctor', '/doctor/profile', '/calendar?kind=surgery', '/surgery/pending'):
        page = client.get(path)
        assert page.status_code == 200
        assert 'has-pending-surgery' in page.text
        assert '1 patient awaiting a surgery date.' in page.text
    assert client.get('/api/surgery/pending').json()['count'] == 1
    # Neither a consultation nor a cancelled surgery resolves the pending month.
    with main.connection() as con:
        slot = month_planning.free_slots(con, 'dr.maya', draft['suggested_month'], 'DEMO-0001')[0]
        con.execute("INSERT INTO surgeries(case_id,surgery_date,slot,status,confirmed_by,rationale,created_at) VALUES(?,?,?,'cancelled','admin.nila','Test cancellation','test')", ('DEMO-0001', slot['date'], slot['slot']))
    assert client.get('/api/surgery/pending').json()['count'] == 1
    monkeypatch.setattr(main.communications, 'send_surgery_whatsapp', lambda *args: {'status': 'stored_not_sent', 'detail': 'Isolated test.'})
    csrf = login(client, 'admin.nila', 'demo-admin')
    result = client.post('/admin/surgery/DEMO-0001/confirm', data={'csrf': csrf, 'surgery_date': slot['date'], 'slot': slot['slot'], 'rationale': 'Admin checked the approved month and calendar.'})
    assert result.status_code == 200
    assert client.get('/api/surgery/pending').json()['count'] == 0
    assert 'has-pending-surgery' not in client.get('/admin').text
    assert 'No surgery dates pending' in client.get('/surgery/pending').text
    with main.connection() as con:
        con.execute("UPDATE surgeries SET status='completed' WHERE case_id='DEMO-0001'")
    assert client.get('/api/surgery/pending').json()['count'] == 0
    with main.connection() as con:
        con.execute("UPDATE surgeries SET status='cancelled' WHERE case_id='DEMO-0001'")
    assert client.get('/api/surgery/pending').json()['count'] == 1


def test_pending_alerts_are_private_and_doctor_scoped(client, monkeypatch):
    for path in ('/api/surgery/pending', '/surgery/pending'):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == (401 if path.startswith('/api/') else 303)
    approved_pending(client, monkeypatch)
    login(client, 'admin.nila', 'demo-admin')
    assert client.get('/api/surgery/pending').json()['count'] == 1
    assert 'Choose a date' in client.get('/surgery/pending').text
    login(client, 'tech.alex', 'demo-tech')
    assert client.get('/api/surgery/pending').json()['count'] == 1
    assert 'Choose a date' not in client.get('/surgery/pending').text
    login(client, 'dr.kamal', 'demo-doctor')
    assert client.get('/api/surgery/pending').json()['count'] == 0
    assert 'DEMO-0001' not in client.get('/surgery/pending').text
    # Login screens never expose the signed-in user's pending patient count.
    assert 'id="pending-surgery-bell"' not in client.get('/login').text


def test_stale_or_out_of_month_bookings_do_not_clear_pending_bell(client, monkeypatch):
    csrf, draft = approved_pending(client, monkeypatch)
    with main.connection() as con:
        other_month = month_planning.shift_month(draft['suggested_month'], 1)
        con.execute("INSERT INTO surgeries(case_id,surgery_date,slot,status,confirmed_by,rationale,created_at) VALUES(?,?,?,'confirmed','admin.nila','Old different month','test')", ('DEMO-0001', other_month+'-01', '09:00'))
    assert client.get('/api/surgery/pending').json()['count'] == 1
    client.post('/api/mobile/patients/DEMO-0001/notes', data={'csrf': csrf, 'symptoms': 'New symptoms need reassessment', 'notes': 'Updated clinical evidence.'})
    login(client, 'admin.nila', 'demo-admin')
    page = client.get('/surgery/pending')
    assert 'must refresh the month approval' in page.text
    assert 'Choose a date' not in page.text
    assert client.get('/api/surgery/pending').json()['count'] == 1
    with main.connection() as con:
        con.execute("UPDATE cases SET is_archived=1 WHERE case_id='DEMO-0001'")
    assert client.get('/api/surgery/pending').json()['count'] == 0


def test_draft_month_alone_does_not_trigger_the_approved_month_bell(client, monkeypatch):
    monkeypatch.setattr(planning_ai, 'choose', lambda *args: {'provider': 'local_planning_rules', 'provider_label': 'Local planning checks'})
    csrf = login(client)
    month_draft(client, csrf)
    assert client.get('/api/surgery/pending').json()['count'] == 0


def test_bell_remains_until_all_pending_patients_have_dates(client, monkeypatch):
    csrf, draft = approved_pending(client, monkeypatch)
    record = client.get('/api/mobile/patients/DEMO-0003').json()
    result = client.post('/api/mobile/patients/DEMO-0003/month', data={'csrf': csrf, 'approved_month': draft['suggested_month'], 'reason': 'Doctor reviewed this second elective planning month.', 'attestation': 'yes', 'evidence_hash': record['evidence_hash'], **draft['assessment']})
    assert result.status_code == 200
    assert client.get('/api/surgery/pending').json()['count'] == 2
    with main.connection() as con:
        con.execute("INSERT INTO surgeries(case_id,surgery_date,slot,status,confirmed_by,rationale,created_at) VALUES(?,?,?,'confirmed','admin.nila','Confirmed test booking','test')", ('DEMO-0001', draft['suggested_month']+'-02', '09:00'))
    assert client.get('/api/surgery/pending').json()['count'] == 1
    page = client.get('/surgery/pending').text
    assert 'DEMO-0003' in page and 'DEMO-0001' not in page
    assert 'has-pending-surgery' in page
