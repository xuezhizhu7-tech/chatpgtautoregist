#!/usr/bin/env python3
"""
Email client: Cloud Mail API + Gmail IMAP fallback.
Create temp emails and retrieve OTP codes.
"""
import json, subprocess, time, random, string, imaplib, email, re
from email.utils import parsedate_to_datetime
from step_01_config.config import CLOUD_MAIL_URL, CLOUD_MAIL_EMAIL, CLOUD_MAIL_PASS, EMAIL_DOMAIN, GMAIL_USER, GMAIL_PASS
from step_02_shared.records import log

CLOUD_MAIL_TOKEN = ""  # runtime cache


def get_cloud_mail_token():
    """获取 cloud-mail API Token"""
    global CLOUD_MAIL_TOKEN
    if CLOUD_MAIL_TOKEN:
        return CLOUD_MAIL_TOKEN
    r = subprocess.run(["curl", "-sS", "--max-time", "10",
        "-H", "Content-Type: application/json",
        "-X", "POST",
        "-d", json.dumps({"email": CLOUD_MAIL_EMAIL, "password": CLOUD_MAIL_PASS}),
        f"{CLOUD_MAIL_URL}/api/public/genToken"],
        capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
        CLOUD_MAIL_TOKEN = data["data"]["token"]
        log(f"  Cloud Mail Token 获取成功")
        return CLOUD_MAIL_TOKEN
    except Exception as e:
        log(f"  Cloud Mail Token 获取失败: {e}")
        return None


def random_email():
    """Create a temp email via Cloud Mail API, return (address, jwt)"""
    token = get_cloud_mail_token()
    if not token:
        return None, None
    prefix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    email_addr = f"{prefix}@{EMAIL_DOMAIN}"
    r = subprocess.run(["curl", "-sS", "--max-time", "10",
        "-H", f"Authorization: {token}",
        "-H", "Content-Type: application/json",
        "-X", "POST",
        "-d", json.dumps({"list": [{"email": email_addr}]}),
        f"{CLOUD_MAIL_URL}/api/public/addUser"],
        capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
        if data.get("code") == 200:
            log(f"  创建邮箱成功: {email_addr}")
            return email_addr, token
        else:
            log(f"  创建邮箱失败: {data}")
            return None, None
    except Exception:
        return None, None


def get_email_otp(target_email, after_ts, timeout=90, jwt=None):
    """Get email OTP via Cloud Mail API (or Gmail IMAP fallback)"""
    deadline = time.time() + timeout
    attempt = 0
    token = get_cloud_mail_token()
    while time.time() < deadline:
        attempt += 1
        if token:
            try:
                r = subprocess.run(["curl", "-sS", "--max-time", "10",
                    "-H", f"Authorization: {token}",
                    "-H", "Content-Type: application/json",
                    "-X", "POST",
                    "-d", json.dumps({"toEmail": target_email, "num": 1, "size": 10, "timeSort": "desc"}),
                    f"{CLOUD_MAIL_URL}/api/public/emailList"],
                    capture_output=True, text=True)
                resp = r.stdout.strip()
                if not resp.startswith("{"):
                    if attempt <= 3:
                        log(f"    [email] attempt {attempt}: bad response: {resp[:80]}")
                    time.sleep(5)
                    continue
                data = json.loads(resp)
                results = data.get("data", [])
                if attempt <= 3:
                    log(f"    [email] attempt {attempt}: {len(results)} mails")
                if not results:
                    time.sleep(5)
                    continue
                for mail_item in results:
                    subj = mail_item.get("subject", "")
                    raw = mail_item.get("content", "") or mail_item.get("text", "")
                    combined = subj + " " + raw
                    if "openai" not in combined.lower() and "verify" not in combined.lower():
                        continue
                    m = re.search(r'(\d{6})', subj)
                    if m:
                        log(f"    [email] Found OTP in subject: {m.group(1)}")
                        return m.group(1)
                    m = re.search(r'>\s*(\d{6})\s*<', raw)
                    if m:
                        log(f"    [email] Found OTP in html: {m.group(1)}")
                        return m.group(1)
                    m = re.search(r'(\d{6})', raw)
                    if m:
                        log(f"    [email] Found OTP in raw: {m.group(1)}")
                        return m.group(1)
                time.sleep(5)
                continue
            except Exception as e:
                if attempt <= 3:
                    log(f"    [email] error: {e}")
        else:
            # Fallback: Gmail IMAP
            try:
                mail = imaplib.IMAP4_SSL("imap.gmail.com")
                mail.login(GMAIL_USER, GMAIL_PASS)
                mail.select("INBOX")
                _, nums = mail.search(None, '(FROM "noreply@tm.openai.com")')
                ids = nums[0].split()
                for mid in reversed(ids[-10:]):
                    _, msg_data = mail.fetch(mid, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])
                    to_h = msg.get("To", "")
                    if target_email.lower() not in to_h.lower():
                        continue
                    try:
                        msg_dt = parsedate_to_datetime(msg.get("Date", ""))
                        if msg_dt.timestamp() < after_ts:
                            continue
                    except Exception:
                        pass
                    subj = msg.get("Subject", "")
                    m = re.search(r'(\d{6})', subj)
                    if m:
                        mail.logout()
                        return m.group(1)
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() in ("text/plain", "text/html"):
                                p = part.get_payload(decode=True)
                                if p: body += p.decode("utf-8", errors="ignore")
                    else:
                        p = msg.get_payload(decode=True)
                        if p: body = p.decode("utf-8", errors="ignore")
                    m = re.search(r'>[\s\r\n]*(\d{6})[\s\r\n]*<', body)
                    if m:
                        mail.logout()
                        return m.group(1)
                mail.logout()
            except Exception:
                pass
        time.sleep(8)
    return None
