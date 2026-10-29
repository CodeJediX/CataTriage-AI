"""Persistent, role-scoped reminders for approved months without a booked date."""
from datetime import datetime


def pending_cases(user):
    from . import main as m

    if not user or user['r'] not in {'admin', 'doctor', 'technician'}:
        return []
    with m.role_connection(m.DOCTOR_DB_PATH) as con:
        sql = 'SELECT case_id,doctor_username FROM patient_profiles'
        args = ()
        if user['r'] == 'doctor':
            sql += ' WHERE doctor_username=?'
            args = (user['u'],)
        assignments = {r['case_id']: r['doctor_username'] for r in con.execute(sql, args)}
    if user['r'] == 'doctor' and not assignments:
        return []
    sql = '''SELECT c.case_id,c.patient_alias,c.approved_tier,p.approved_month,
                    p.doctor_username AS approving_doctor
             FROM cases c JOIN surgery_month_plans p ON p.case_id=c.case_id
             WHERE c.is_archived=0 AND p.approved_month IS NOT NULL AND p.approved_month<>''
             AND NOT EXISTS (
                 SELECT 1 FROM surgeries s WHERE s.case_id=c.case_id
                 AND s.status IN ('confirmed','completed') AND substr(s.surgery_date,1,7)=p.approved_month
                 AND s.slot IS NOT NULL AND s.slot<>''
             )'''
    args = ()
    if user['r'] == 'doctor':
        sql += ' AND c.case_id IN (' + ','.join('?' for _ in assignments) + ')'
        args = tuple(assignments)
    sql += ' ORDER BY p.approved_month,c.patient_alias,c.case_id'
    with m.connection() as con:
        rows = [dict(row) for row in con.execute(sql, args)]
    for row in rows:
        row['doctor_username'] = assignments.get(row['case_id'], '')
        row['month_label'] = datetime.strptime(row['approved_month'], '%Y-%m').strftime('%B %Y')
    return rows


def for_request(request, user):
    if not hasattr(request.state, 'pending_surgery_cases'):
        request.state.pending_surgery_cases = pending_cases(user)
    return request.state.pending_surgery_cases
