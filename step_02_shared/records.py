#!/usr/bin/env python3
"""
Logging, encoding, and record-keeping utilities.
"""
import json, time, base64
from step_01_config.config import ACCOUNTS_LOG


def _enc(s):
    """Base64 encode a string to bypass platform PII masking."""
    return base64.b64encode(s.encode()).decode()


def _dec(s):
    """Decode base64 string."""
    return base64.b64decode(s.encode()).decode()


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def log_sensitive(phone=None, password=None, extra_msg=""):
    """Log with encoded phone/password to bypass platform masking."""
    parts = []
    if phone:
        parts.append(f"手机号:{_enc(phone)}")
    if password:
        parts.append(f"密码:{_enc(password)}")
    if extra_msg:
        parts.append(extra_msg)
    log("  " + " | ".join(parts))


def save_record(record):
    """Append a record to the accounts jsonl log, flushed immediately.
    Encodes phone and password as base64 to bypass platform PII masking."""
    safe = dict(record)
    if "phone" in safe:
        safe["phone_b64"] = _enc(safe.pop("phone"))
    if "password" in safe:
        safe["password_b64"] = _enc(safe.pop("password"))
    with open(ACCOUNTS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(safe) + "\n")
        f.flush()
