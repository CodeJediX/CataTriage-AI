"""Session revocation and bounded password-authentication attempts."""
import hashlib
import time


def state(con,username):
    row=con.execute("SELECT * FROM account_security WHERE username=?",(username,)).fetchone()
    return dict(row) if row else {"password_epoch":0,"must_change":0,"temporary_expires":0,"firebase_linked":0,"firebase_pending":0}


def attempt_key(request,username):
    address=request.client.host if request.client else "unknown"
    return hashlib.sha256((address+"|"+username.lower()).encode()).hexdigest()


def blocked(con,key):
    row=con.execute("SELECT failures,started_at FROM authentication_attempts WHERE attempt_key=?",(key,)).fetchone()
    return bool(row and row[0]>=5 and time.time()-row[1]<900)


def failed(con,key):
    now=int(time.time())
    con.execute("DELETE FROM authentication_attempts WHERE started_at<?",(now-86400,))
    con.execute("""INSERT INTO authentication_attempts(attempt_key,failures,started_at) VALUES(?,1,?)
        ON CONFLICT(attempt_key) DO UPDATE SET failures=CASE WHEN authentication_attempts.started_at<? THEN 1 ELSE authentication_attempts.failures+1 END,
        started_at=CASE WHEN authentication_attempts.started_at<? THEN excluded.started_at ELSE authentication_attempts.started_at END""",(key,now,now-900,now-900))


def changed(con,username,temporary=False):
    con.execute("""INSERT INTO account_security(username,password_epoch,must_change,temporary_expires) VALUES(?,1,?,?)
        ON CONFLICT(username) DO UPDATE SET password_epoch=account_security.password_epoch+1,must_change=excluded.must_change,temporary_expires=excluded.temporary_expires""",
        (username,int(temporary),int(time.time())+86400 if temporary else 0))


def invalidate_sessions(con,username):
    con.execute("""INSERT INTO account_security(username,password_epoch) VALUES(?,1)
        ON CONFLICT(username) DO UPDATE SET password_epoch=account_security.password_epoch+1""",(username,))
