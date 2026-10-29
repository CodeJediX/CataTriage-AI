"""Editable login names preserve immutable account IDs and clinical audit ownership."""
import re
from fastapi import HTTPException
from . import account_security
from .database import verify_password,now_iso


def login_name(con,username):
    row=con.execute('SELECT login_name FROM account_login_names WHERE username=?',(username,)).fetchone()
    return row[0] if row else username


def resolve_login(con,value):
    value=value.strip().lower()
    row=con.execute('SELECT username FROM account_login_names WHERE login_name=?',(value,)).fetchone()
    if row: return row[0]
    row=con.execute('SELECT username FROM users WHERE username=? AND NOT EXISTS(SELECT 1 FROM account_login_names WHERE username=?)',(value,value)).fetchone()
    return row[0] if row else None


def update_login(con,username,new_name,current_password):
    value=new_name.strip().lower()
    if value==login_name(con,username): return False
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{2,59}',value): raise HTTPException(400,'Use 3–60 lowercase letters, numbers, dots, hyphens or underscores for the username.')
    row=con.execute('SELECT password_hash FROM users WHERE username=? AND role=\'doctor\'',(username,)).fetchone()
    key='profile-rename:'+username
    if account_security.blocked(con,key): raise HTTPException(429,'Too many attempts. Try again in 15 minutes.')
    if not row or not verify_password(current_password,row[0]): raise HTTPException(400,'Verify your current password to change the username.')
    collision=con.execute('SELECT username FROM users WHERE username=? AND username<>?',(value,username)).fetchone()
    alias=con.execute('SELECT username FROM account_login_names WHERE login_name=? AND username<>?',(value,username)).fetchone()
    if collision or alias: raise HTTPException(409,'This username is already in use.')
    con.execute('INSERT INTO account_login_names(username,login_name,updated_at) VALUES(?,?,?) ON CONFLICT(username) DO UPDATE SET login_name=excluded.login_name,updated_at=excluded.updated_at',(username,value,now_iso()))
    account_security.invalidate_sessions(con,username)
    return True
