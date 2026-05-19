#!/usr/bin/env python3
"""
Phase 2: OAuth Login + Sub2API Import
- Read registered accounts from jsonl log
- OAuth login with phone + password
- Add email, verify, consent
- Import to Sub2API

Usage:
  python oauth_import.py                    # Import all un-imported accounts
  python oauth_import.py --count 5          # Import at most 5 accounts
  python oauth_import.py --file accounts.jsonl  # Use custom jsonl file
"""
import json, subprocess, asyncio, websockets, time, random, sys, os, argparse
from urllib.parse import urlparse, parse_qs

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from step_02_shared.records import log, log_sensitive, save_record, _enc, _dec
from step_03_clients.sms_client import apply_country_override
from step_03_clients.mail_client import random_email, get_email_otp
from step_03_clients.sub2api_client import sub2api_request, sub2api_login, generate_auth_url
from step_02_shared.browser_cdp import CDP, restart_chrome_with_fingerprint
from step_01_config.config import CDP_PORT, ACCOUNTS_LOG

# Parse CLI args
_parser = argparse.ArgumentParser(description="OAuth import registered accounts to Sub2API")
_parser.add_argument("--count", type=int, default=0, help="Max accounts to import (0=all)")
_parser.add_argument("--file", type=str, default=ACCOUNTS_LOG, help="Path to accounts jsonl")
_parser.add_argument("--country", type=int, help="Override country ID")
_parser.add_argument("--dial", type=str, help="Override dial code")
_parser.add_argument("--iso", type=str, help="Override ISO code")
_parser.add_argument("--no-proxy", action="store_true", help="Ignored; proxy mode is disabled")
_args, _ = _parser.parse_known_args()

# Build country config from overrides
country_cfg = apply_country_override(
    country_id=_args.country,
    dial=_args.dial,
    iso=_args.iso,
)
use_proxy = False


def load_pending_accounts(jsonl_path, max_count=0):
    """Load accounts that are registered but not yet imported.
    Returns list of dicts with phone, password (decoded from base64)."""
    accounts = []
    if not os.path.exists(jsonl_path):
        log(f"  账号文件不存在: {jsonl_path}")
        return accounts

    # Track which phones have been successfully imported
    imported_phones = set()
    registered_phones = []

    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)

            # Decode phone/password from base64
            phone = rec.get("phone_b64")
            if phone:
                phone = _dec(phone)
            else:
                phone = rec.get("phone", "")

            password = rec.get("password_b64")
            if password:
                password = _dec(password)
            else:
                password = rec.get("password", "")

            status = rec.get("status", "")
            phase = rec.get("phase", 0)

            if phase == 2 and status == "imported":
                imported_phones.add(phone)
            elif phase == 1 and status == "registered":
                registered_phones.append({"phone": phone, "password": password})

    # Return registered accounts that haven't been imported yet
    for acc in registered_phones:
        if acc["phone"] not in imported_phones:
            accounts.append(acc)
            if max_count > 0 and len(accounts) >= max_count:
                break

    return accounts


async def oauth_import(phone, password, account_email, token, email_jwt=None):
    """OAuth login with phone+password -> add-email -> Sub2API import"""
    oauth_url, session_id, state = generate_auth_url(token)
    log(f"  OAuth 会话: {session_id[:16]}")

    r = subprocess.run(["curl", "-sS", "--max-time", "3", f"http://127.0.0.1:{CDP_PORT}/json/list"],
                      capture_output=True, text=True)
    targets = json.loads(r.stdout)
    page = [t for t in targets if t.get("type") == "page"][0]

    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=10**7, open_timeout=10) as ws:
        cdp = CDP(ws)

        async def log_human_check(label):
            """Log visible human-verification/challenge signals when OpenAI shows them."""
            info = await cdp.ev(r"""(function(){
                var text = (document.body && document.body.innerText || '').replace(/\s+/g, ' ').trim();
                var title = document.title || '';
                var url = location.href || '';
                var iframes = Array.from(document.querySelectorAll('iframe')).map(function(f){ return f.src || ''; }).filter(Boolean);
                var inputs = Array.from(document.querySelectorAll('input')).map(function(i){ return (i.name || '') + ' ' + (i.id || '') + ' ' + (i.type || ''); }).join(' ');
                var combined = (title + ' ' + url + ' ' + text + ' ' + iframes.join(' ') + ' ' + inputs).toLowerCase();
                var keywords = [
                    'verify you are human', 'verify that you are human', 'confirm you are human',
                    'human verification', 'security check', 'checking your browser', 'just a moment',
                    'challenge', 'captcha', 'turnstile', 'cf-turnstile', 'recaptcha', 'hcaptcha',
                    'cloudflare', '人机', '真人', '验证你是真人', '安全验证'
                ];
                var hits = keywords.filter(function(k){ return combined.indexOf(k) >= 0; });
                var turnstileCount = document.querySelectorAll('[name="cf-turnstile-response"], .cf-turnstile').length;
                var captchaFrames = iframes.filter(function(src){ return /turnstile|captcha|recaptcha|hcaptcha|cloudflare/i.test(src); });
                return JSON.stringify({
                    detected: hits.length > 0 || turnstileCount > 0 || captchaFrames.length > 0,
                    title: title,
                    url: url,
                    hits: hits,
                    turnstileCount: turnstileCount,
                    captchaFrames: captchaFrames.slice(0,3),
                    text: text.substring(0,180)
                });
            })()""")
            if not info:
                return False
            try:
                data = json.loads(info)
            except Exception:
                log(f"  [{label}] 人机验证检测结果解析失败: {str(info)[:160]}")
                return False
            if data.get("detected"):
                log(f"  [{label}] ⚠ 检测到人机验证/安全挑战: title={data.get('title')!r}, hits={data.get('hits')}, turnstile={data.get('turnstileCount')}, frames={data.get('captchaFrames')}")
                log(f"  [{label}] 人机验证页面文本: {data.get('text')}")
                return True
            return False

        # Inject fingerprint + clear cookies
        await cdp.inject_fingerprint()
        await cdp.send("Network.clearBrowserCookies")
        await asyncio.sleep(0.5)
        await cdp.ev(f"window.location.href = '{oauth_url}'")
        await asyncio.sleep(8)
        await cdp.inject_fingerprint()

        url = await cdp.url()
        log(f"  [O1] 已打开 OAuth 页面: {url}")
        await log_human_check("O1")

        # Click "Continue with phone"
        await cdp.ev("""(function(){
            var btns = Array.from(document.querySelectorAll('button'));
            var p = btns.find(function(b){
                var t = b.textContent.toLowerCase();
                return t.includes('phone') || t.includes('电话');
            });
            if(p) p.click();
        })()""")
        await asyncio.sleep(4)

        # Input phone number
        dial_code = country_cfg["dial"]
        local_phone = phone[len(dial_code):] if phone.startswith(dial_code) else phone
        # Select country
        await cdp.ev(f"""(function(){{
            var sel = document.querySelector('select');
            if(sel) {{
                sel.value = '{country_cfg["iso"]}';
                sel.dispatchEvent(new Event('change', {{bubbles: true}}));
            }}
        }})()""")
        await asyncio.sleep(1)
        await cdp.focus_and_type('input[type="tel"]', local_phone)
        await asyncio.sleep(0.5)
        phone_review = await cdp.ev(r"""(function(){
            var input = document.querySelector('input[type="tel"]');
            var hidden = document.querySelector('input[type="hidden"][name="phone"], input[name="phone"]');
            var submit = document.querySelector('button[type="submit"]') || Array.from(document.querySelectorAll('button')).find(function(b){
                return /continue|继续/i.test(b.textContent || '');
            });
            return JSON.stringify({
                local_phone: arguments[0],
                renderedValue: input ? input.value : null,
                hidden: hidden ? {name:hidden.name || '', id:hidden.id || '', value:hidden.value || ''} : null,
                submitButton: submit ? {
                    present: true,
                    text: (submit.textContent || '').trim().substring(0, 80),
                    disabled: !!submit.disabled,
                    ariaDisabled: submit.getAttribute('aria-disabled') || '',
                    type: submit.type || ''
                } : {present:false}
            });
        })(%s)""" % json.dumps(local_phone))
        log(f"  [O2] 手机号提交前复查 {phone_review}")
        await cdp.click_submit()
        await asyncio.sleep(6)
        url = await cdp.url()
        log(f"  [O2] 提交手机号后: {url}")
        await log_human_check("O2")

        # Should be on password page
        if "password" not in (url or ""):
            log(f"  ✗ 未进入密码页: {url}")
            return "no_password_page"

        # Enter password
        await asyncio.sleep(1)
        await cdp.ev('var el=document.querySelector(\'input[type="password"]\'); if(el){el.focus(); el.click();}')
        await asyncio.sleep(0.3)
        for ch in password:
            await cdp.send("Input.dispatchKeyEvent", {
                "type": "keyDown", "text": ch, "key": ch,
                "code": "", "windowsVirtualKeyCode": ord(ch)
            })
            await cdp.send("Input.dispatchKeyEvent", {
                "type": "keyUp", "key": ch,
                "code": "", "windowsVirtualKeyCode": ord(ch)
            })
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.3)
        pwd_len = await cdp.ev('document.querySelector(\'input[type="password"]\')?.value?.length || 0')
        log(f"  [O3a] 密码框长度: {pwd_len}")
        await asyncio.sleep(0.5)
        await cdp.click_submit()
        await asyncio.sleep(3)
        # Fallback: press Enter if still on password page
        url_now = await cdp.url()
        if "log-in/password" in (url_now or "") or "password" in (url_now or ""):
            await cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            await cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            await asyncio.sleep(4)

        url = await cdp.url()
        log(f"  [O3] 提交密码后: {url}")
        await log_human_check("O3")

        # If still on password page after first attempt, diagnose and retry
        if "password" in (url or ""):
            diag = await cdp.ev("""(function(){
                var inputs = Array.from(document.querySelectorAll('input')).map(function(i){
                    return {name:i.name, type:i.type, value_len:(i.value||'').length, disabled:i.disabled};
                });
                var errors = Array.from(document.querySelectorAll('[role="alert"],.error,.field-error,.form-error,.msg-error')).map(function(e){ return e.textContent.trim().substring(0,120); });
                var buttons = Array.from(document.querySelectorAll('button')).map(function(b){
                    return {text:b.textContent.trim().substring(0,60), disabled:b.disabled};
                });
                return JSON.stringify({inputs:inputs, errors:errors, buttons:buttons});
            })()""")
            log(f"  [O3d] 仍停留在密码页，诊断信息: {diag}")

            # Retry: re-focus password field, re-type, and click submit
            log("  [O3d] 正在重新提交密码...")
            await cdp.ev('var el=document.querySelector(\'input[type="password"]\'); if(el){el.focus(); el.click();}')
            await asyncio.sleep(0.3)
            await cdp.click_submit()
            await asyncio.sleep(4)

            url = await cdp.url()
            log(f"  [O3d] 重试后: {url}")
            await log_human_check("O3d")

            # Still stuck? Log page text snippet for more context
            if "password" in (url or ""):
                text = await cdp.text(300)
                log(f"  [O3d] 页面文本: {text}")

        # Handle add-email
        if "add-email" in (url or ""):
            log("  [O4] 进入添加邮箱页")
            otp_ts = time.time() - 10
            await cdp.focus_and_type('input[type="email"]', account_email)
            await asyncio.sleep(0.3)
            await cdp.click_submit()
            await asyncio.sleep(6)
            url = await cdp.url()
            log(f"  [O4b] 提交邮箱后: {url}")
            await log_human_check("O4b")

            if "email-verification" in (url or "") or "verify" in (url or ""):
                email_page_info = await cdp.ev(r"""(function(){
                    var text = (document.body && document.body.innerText || '').replace(/\s+/g, ' ');
                    var expected = arguments[0];
                    var visibleEmails = Array.from(text.matchAll(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/ig)).map(function(m){ return m[0]; });
                    return JSON.stringify({
                        expectedEmail: expected,
                        visibleEmails: visibleEmails.slice(0, 5),
                        emailMatches: visibleEmails.some(function(e){ return e.toLowerCase() === expected.toLowerCase(); })
                    });
                })(%s)""" % json.dumps(account_email))
                log(f"  [O5] 验证码页显示邮箱检查: {email_page_info}")
                log("  [O5] 正在等待邮箱验证码...")
                otp = await asyncio.to_thread(get_email_otp, account_email, otp_ts, 90, email_jwt)
                if not otp:
                    log("  ✗ 未收到邮箱验证码！")
                    return "email_otp_failed"
                log(f"  [O5] 邮箱验证码: {otp}")
                await cdp.focus_and_type('input', otp)
                await asyncio.sleep(0.3)
                await cdp.click_submit()
                await asyncio.sleep(8)
                url = await cdp.url()
                log(f"  [O6] 提交邮箱验证码后: {url}")
                await log_human_check("O6")

        # Handle consent page
        if "consent" in (url or ""):
            log("  [O7] 进入授权页，正在点击允许/继续...")
            btn_texts = await cdp.ev("""Array.from(document.querySelectorAll('button')).map(function(b){ return b.textContent.trim().substring(0,60); })""")
            log(f"  [O7] 找到的按钮: {btn_texts}")

            async def trigger_consent_continue():
                return await cdp.ev("""(function(){
                    var forms = Array.from(document.querySelectorAll('form'));
                    var visibleForms = forms.filter(function(f){ return f.offsetParent !== null || f.getClientRects().length; });
                    var form = visibleForms[visibleForms.length - 1] || forms[forms.length - 1];
                    if(form && form.requestSubmit) { form.requestSubmit(); return 'requestSubmit'; }
                    var btns = Array.from(document.querySelectorAll('button'));
                    var targets = ['allow', 'continue', 'authorize', 'accept', 'agree', 'yes', 'confirm'];
                    for(var i = 0; i < targets.length; i++) {
                        var btn = btns.find(function(b){ return b.textContent.trim().toLowerCase().includes(targets[i]); });
                        if(btn && !btn.disabled) { btn.click(); return 'clicked:' + targets[i]; }
                    }
                    for(var j = btns.length - 1; j >= 0; j--) {
                        if(!btns[j].disabled && btns[j].offsetParent !== null) { btns[j].click(); return 'clicked:last'; }
                    }
                    return 'no_button_found';
                })()""")

            clicked = "not_attempted"
            for consent_attempt in range(1, 6):
                clicked = await trigger_consent_continue()
                log(f"  [O7] 授权触发结果（第 {consent_attempt}/5 轮）: {clicked}")
                await asyncio.sleep(3)
                url = await cdp.url()
                if "consent" not in (url or ""):
                    break
            if "consent" in (url or ""):
                await cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
                await cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
                await asyncio.sleep(5)
                url = await cdp.url()
            log(f"  [O7b] 授权后: {url}")
            await log_human_check("O7b")

        # Check for callback
        if "callback" in (url or "") or "localhost:1455" in (url or "") or "chrome-error" in (url or ""):
            if "chrome-error" in (url or ""):
                nav = await cdp.send("Page.getNavigationHistory")
                if nav and "result" in nav:
                    entries = nav["result"].get("entries", [])
                    for entry in reversed(entries):
                        if "localhost:1455" in entry.get("url", ""):
                            url = entry["url"]
                            break
                log(f"  [O7c] 已从导航历史获取回调地址: {url[:80]}...")

            if "localhost:1455" in (url or "") and "code=" in (url or ""):
                log("  [O8] ✓ 已获取回调！")
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                code = params.get("code", [""])[0]
                cb_state = params.get("state", [""])[0]

                if not code:
                    log("  ✗ 回调 URL 中没有 code！")
                    return "no_callback_code"

                log("  [O9] 正在交换 code...")
                exchange_body = {"session_id": session_id, "code": code}
                if cb_state:
                    exchange_body["state"] = cb_state
                elif state:
                    exchange_body["state"] = state

                exc = sub2api_request("POST", "/api/v1/admin/openai/exchange-code",
                    token=token, data=exchange_body)

                if exc.get("code") != 0:
                    log(f"  ✗ code 交换失败: {json.dumps(exc)[:200]}")
                    return "exchange_failed"

                log("  [O10] 正在 Sub2API 中创建账号...")
                name = account_email.split("@")[0]
                acc = sub2api_request("POST", "/api/v1/admin/accounts",
                    token=token, data={
                        "name": name, "platform": "openai", "type": "oauth",
                        "credentials": exc["data"],
                        "concurrency": 10, "group_ids": [2],
                        "priority": 1, "rate_multiplier": 1,
                        "auto_pause_on_expired": True
                    })

                if acc.get("code") == 0:
                    log(f"  [O11] ✓✓✓ 账号已导入！ID: {acc['data'].get('id')}")
                    return True
                else:
                    log(f"  ✗ 账号创建失败: {json.dumps(acc)[:200]}")
                    return "account_create_failed"
            else:
                log(f"  ✗ URL 中未找到回调 code: {url}")
                return "no_callback_code"

        log(f"  ✗ OAuth 失败，最终 URL: {url}")
        await log_human_check("OFINAL")
        text = await cdp.text(200)
        log(f"  页面文本: {text}")
        return "oauth_failed"


async def main():
    max_count = _args.count if _args.count > 0 else 0

    # Load pending accounts
    pending = load_pending_accounts(_args.file, max_count)
    if not pending:
        log("没有待导入账号。")
        return

    log("=" * 60)
    log(f"  OAuth 导入（{len(pending)} 个账号）")
    log(f"  代理: {'已启用' if use_proxy else '已禁用（直连）'}")
    log("=" * 60)

    # Login Sub2API once
    token = sub2api_login()
    log(f"[0] Sub2API 登录成功")

    success = 0
    failed = 0

    for i, acc in enumerate(pending, 1):
        phone = acc["phone"]
        password = acc["password"]

        log(f"\n{'='*60}")
        log(f"  账号 {i}/{len(pending)} - {phone}")
        log(f"{'='*60}")

        # Restart Chrome with fresh fingerprint
        log("[指纹] 正在使用新配置重启 Chrome...")
        restart_chrome_with_fingerprint(use_proxy=use_proxy)
        await asyncio.sleep(3)

        # Create temp email for this account
        account_email, email_jwt = random_email()
        if not account_email:
            log("  ✗ 创建临时邮箱失败，跳过...")
            failed += 1
            save_record({
                "email": None,
                "phone": phone,
                "password": password,
                "phase": 2,
                "status": "email_create_failed",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
            })
            continue

        log(f"  邮箱: {account_email}")

        # OAuth import
        result = await oauth_import(phone, password, account_email, token, email_jwt)

        if result is True:
            success += 1
            save_record({
                "email": account_email,
                "phone": phone,
                "password": password,
                "phase": 2,
                "status": "imported",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
            })
            log(f"  ✓ DONE! Total: {success} success, {failed} failed")
        else:
            failed += 1
            status = result if isinstance(result, str) else "oauth_failed"
            save_record({
                "email": account_email,
                "phone": phone,
                "password": password,
                "phase": 2,
                "status": status,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
            })
            log(f"  ✗ OAuth failed ({status}). Total: {success} success, {failed} failed")

        # Random delay between accounts
        if i < len(pending):
            delay = random.randint(15, 45)
            log(f"  等待 {delay} 秒后处理下一个账号...")
            await asyncio.sleep(delay)

    summary = {"success": success, "failed": failed, "total": len(pending)}
    log(f"\n{'='*60}")
    log(f"  FINAL: {success} imported, {failed} failed out of {len(pending)}")
    log(f"{'='*60}")
    print(f"__SUMMARY_JSON__{json.dumps(summary)}")

if __name__ == "__main__":
    asyncio.run(main())
