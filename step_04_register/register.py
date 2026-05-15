#!/usr/bin/env python3
"""
Phase 1: Batch ChatGPT Account Registration
- Buy phone numbers via HeroSMS
- Register new accounts with phone + SMS verification
- Save results to accounts jsonl (for later OAuth import)
"""
import json, subprocess, asyncio, websockets, time, random, sys, argparse, os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from step_02_shared.records import log, log_sensitive, save_record, _enc, _dec
from step_03_clients.sms_client import buy_number, cancel_number, finish_number, get_sms, apply_country_override
from step_02_shared.browser_cdp import CDP, restart_chrome_with_fingerprint
from step_01_config.config import CDP_PORT, DEFAULT_PASSWORD, ACCOUNTS_LOG

# Parse CLI args
_parser = argparse.ArgumentParser(description="Batch register ChatGPT accounts")
_parser.add_argument("count", nargs="?", type=int, default=2, help="Number of accounts to register")
_parser.add_argument("--country", type=int, help="Override country ID")
_parser.add_argument("--dial", type=str, help="Override dial code")
_parser.add_argument("--iso", type=str, help="Override ISO code")
_parser.add_argument("--no-proxy", action="store_true", help="Disable proxy (direct connection)")
_args, _ = _parser.parse_known_args()

# Build country config from overrides (returns dict, no mutable globals)
country_cfg = apply_country_override(
    country_id=_args.country,
    dial=_args.dial,
    iso=_args.iso,
)
use_proxy = not _args.no_proxy


def random_password():
    return DEFAULT_PASSWORD


async def register_account():
    """Register new account with phone number. Returns dict or None."""
    act_id, phone, country_cfg = buy_number()
    if not act_id:
        log("  鉁?Failed to buy number")
        return None

    password = random_password()
    log_sensitive(phone=f"+{phone}", password=password)

    # Connect to browser
    r = subprocess.run(["curl", "-sS", "--max-time", "3", f"http://127.0.0.1:{CDP_PORT}/json/list"],
                      capture_output=True, text=True)
    targets = json.loads(r.stdout)
    page = [t for t in targets if t.get("type") == "page"][0]

    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=10**7, open_timeout=10) as ws:
        cdp = CDP(ws)

        # Inject fingerprint protection
        await cdp.inject_fingerprint()

        # Clear cookies + navigate to chatgpt.com
        await cdp.send("Network.clearBrowserCookies")
        await asyncio.sleep(0.5)
        await cdp.send('Page.navigate', {'url': 'https://chatgpt.com/auth/login'})
        await asyncio.sleep(10)

        # Re-inject after navigation
        await cdp.inject_fingerprint()

        url = await cdp.url()
        log(f"  [1] Landed: {url}")

        # Wait for page to fully load
        for wait_i in range(15):
            title = await cdp.ev("document.title || ''")
            body_len = await cdp.ev("document.body ? document.body.innerText.length : 0")
            if wait_i == 0 or wait_i == 5:
                snip = await cdp.ev("document.body ? document.body.innerText.substring(0,100) : ''")
                log(f"    [wait {wait_i}] title={title} len={body_len} text={str(snip)[:80]}")
            if title and "moment" not in title.lower() and "just" not in title.lower() and body_len and body_len > 20:
                break
            await asyncio.sleep(5)

        # Handle "Unable to load site" / VPN error
        body_text = await cdp.ev("document.body ? document.body.innerText.substring(0,200) : ''")
        if "unable to load" in (body_text or "").lower() or "vpn" in (body_text or "").lower():
            log("  [!] Site blocked, retrying...")
            await cdp.ev("location.reload()")
            await asyncio.sleep(8)
            body_text = await cdp.ev("document.body ? document.body.innerText.substring(0,200) : ''")
            if "unable to load" in (body_text or "").lower():
                log("  鉁?Site still blocked after retry")
                cancel_number(act_id)
                save_record({
                    "phone": f"+{phone}" if phone else None,
                    "password": password,
                    "phase": 1,
                    "status": "site_blocked",
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
                })
                return None

        # Detect UI type and navigate to phone registration
        has_inline_auth = await cdp.ev("""
            !!Array.from(document.querySelectorAll("button"))
                .find(function(e) { return /Continue with Google|More options/i.test(e.textContent); })
        """)

        if has_inline_auth:
            log("  [2] Inline auth UI detected")
            phone_clicked = await cdp.ev("""(function(){
                var btns = Array.from(document.querySelectorAll('button'));
                var p = btns.find(function(b){ return /phone/i.test(b.textContent); });
                if(p) { p.click(); return true; }
                return false;
            })()""")
            if not phone_clicked:
                log("    Clicking 'More options' first...")
                await cdp.ev("""(function(){
                    var btns = Array.from(document.querySelectorAll('button'));
                    var p = btns.find(function(b){ return /more options/i.test(b.textContent); });
                    if(p) p.click();
                })()""")
                await asyncio.sleep(3)
                await cdp.ev("""(function(){
                    var btns = Array.from(document.querySelectorAll('button'));
                    var p = btns.find(function(b){ return /phone/i.test(b.textContent); });
                    if(p) p.click();
                })()""")
            await asyncio.sleep(4)
        else:
            log("  [2] Old UI - clicking Sign up...")
            clicked = await cdp.ev("""(function(){
                var els = Array.from(document.querySelectorAll("a, button, [role=button]"));
                var el = els.find(function(e) { return /sign up/i.test(e.textContent); });
                if(el) { el.click(); return true; }
                return false;
            })()""")
            if not clicked:
                log("  [!] No Sign up button, trying direct URL...")
                await cdp.ev("window.location.href = 'https://auth.openai.com/log-in-or-create-account?usernameKind=phone_number'")
                await asyncio.sleep(8)
                await cdp.inject_fingerprint()
            else:
                for i in range(15):
                    await asyncio.sleep(4)
                    url = await cdp.url()
                    title = await cdp.ev("document.title || ''")
                    if url and "auth.openai.com" in url:
                        if title and "moment" not in title.lower():
                            break

                url = await cdp.url()
                if "auth.openai.com" not in (url or ""):
                    log(f"  [!] Not on auth page: {url}, trying direct URL...")
                    await cdp.ev("window.location.href = 'https://auth.openai.com/log-in-or-create-account?usernameKind=phone_number'")
                    await asyncio.sleep(8)
                    await cdp.inject_fingerprint()
                else:
                    await asyncio.sleep(3)
                    await cdp.inject_fingerprint()
                    await cdp.ev("""(function(){
                        var btns = Array.from(document.querySelectorAll('button'));
                        var p = btns.find(function(b){ return /phone/i.test(b.textContent); });
                        if(p) p.click();
                    })()""")
                    await asyncio.sleep(4)

        # Verify we have the phone input
        has_tel = False
        for check_i in range(8):
            has_tel = await cdp.ev("!!document.querySelector(\"input[type='tel']\")")
            if has_tel:
                break
            await asyncio.sleep(2)

        if not has_tel:
            log("  [!] No tel input found, trying direct phone registration URL...")
            await cdp.ev("window.location.href = 'https://auth.openai.com/log-in-or-create-account?usernameKind=phone_number'")
            await asyncio.sleep(8)
            await cdp.inject_fingerprint()
            has_tel = await cdp.ev("!!document.querySelector(\"input[type='tel']\")")
            if not has_tel:
                url = await cdp.url()
                body = await cdp.ev("document.body ? document.body.innerText.substring(0,200) : ''")
                log(f"  鉁?Cannot reach phone input. URL: {url}")
                log(f"    Body: {body[:100]}")
                cancel_number(act_id)
                save_record({
                    "phone": f"+{phone}" if phone else None,
                    "password": password,
                    "phase": 1,
                    "status": "no_phone_input",
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
                })
                return None

        url = await cdp.url()
        log(f"  [2] Ready for phone input: {url}")

        # Input phone number
        full_phone = f"+{phone}"
        await cdp.focus_and_type('input[type="tel"]', full_phone)
        await asyncio.sleep(1)

        # Click Continue
        await cdp.click_submit()
        await asyncio.sleep(8)
        url = await cdp.url()
        log(f"  [4] After phone submit: {url}")

        # Check if number already registered
        if "log-in/password" in (url or ""):
            log("  [!] Number already registered, marking failed without retry.")
            cancel_number(act_id)
            save_record({
                "phone": f"+{phone}",
                "password": password,
                "phase": 1,
                "status": "already_registered",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
            })
            log("  [log] Already-registered number recorded")
            return {"phone": phone, "password": password, "act_id": act_id, "reg_failed": True, "status": "already_registered", "recorded": True}

        # Should be on create-account/password page
        if "password" not in (url or ""):
            await asyncio.sleep(4)
            url = await cdp.url()
            log(f"  [4b] Recheck: {url}")

        if "password" not in (url or ""):
            log(f"  鉁?Unexpected page: {url}")
            cancel_number(act_id)
            save_record({
                "phone": f"+{phone}",
                "password": password,
                "phase": 1,
                "status": "unexpected_page",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
            })
            return None

        # Set password
        await cdp.ev("var el=document.querySelector('input[type=\"password\"]'); if(el){el.focus(); el.click();}")
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
        await asyncio.sleep(0.5)
        pwd_len = await cdp.ev("document.querySelector('input[type=\"password\"]')?.value?.length || 0")
        log(f"  [5] Password typed char-by-char, length={pwd_len}")
        if not pwd_len or pwd_len == 0:
            log("  [5] WARNING: password field still empty after typing!")

        # Dismiss password popup
        await cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
        await cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
        await asyncio.sleep(0.3)
        await cdp.click_submit()
        await asyncio.sleep(10)
        url = await cdp.url()

        # Handle timeout errors and retry
        page_text = ""
        for retry_i in range(3):
            page_text = await cdp.text(300) or ""
            if "timed out" in page_text.lower() or "error occurred" in page_text.lower():
                log(f"  [5r] Timeout/error detected (attempt {retry_i+1}/3), clicking Try again...")
                await cdp.ev("""(function(){
                    var btns = Array.from(document.querySelectorAll('button, a'));
                    var btn = btns.find(function(b){ return b.textContent.trim().toLowerCase().includes('try again'); });
                    if(btn) { btn.click(); return 'clicked'; }
                    location.reload();
                    return 'reloaded';
                })()""")
                await asyncio.sleep(8)
                url = await cdp.url()
                if "password" in (url or ""):
                    await cdp.type_password(password)
                    await asyncio.sleep(0.5)
                    await cdp.click_submit()
                    await asyncio.sleep(10)
                    url = await cdp.url()
                    page_text = await cdp.text(200) or ""
                    if "timed out" not in page_text.lower():
                        break
            elif "create-account/password" in (url or ""):
                log("  [5r] Still on password page, retrying submit...")
                await cdp.click_submit()
                await asyncio.sleep(10)
                url = await cdp.url()
            else:
                break

        log(f"  [5] After password: {url}")

        if "create-account/password" in (url or "") or "error" in page_text.lower():
            fail_title = await cdp.ev("document.title || ''")
            fail_text = await cdp.text(800) or ""
            fail_buttons = await cdp.ev("""Array.from(document.querySelectorAll('button')).map(function(b){
                return {
                    text: b.textContent.trim().substring(0, 80),
                    disabled: !!b.disabled,
                    type: b.type || ''
                };
            })""")
            fail_inputs = await cdp.ev("""Array.from(document.querySelectorAll('input')).map(function(i){
                return {
                    type: i.type || '',
                    name: i.name || '',
                    autocomplete: i.autocomplete || '',
                    value_len: (i.value || '').length
                };
            })""")
            fail_errors = await cdp.ev("""Array.from(document.querySelectorAll('[role="alert"], .error, [data-testid*="error"], [class*="error"]')).map(function(e){
                return e.textContent.trim().substring(0, 160);
            }).filter(Boolean)""")
            pwd_len_final = await cdp.ev("document.querySelector('input[type=\"password\"]')?.value?.length || 0")
            log("  Password submit failed after retries")
            log(f"  [5e] url={url}, title={fail_title}, password_len={pwd_len_final}")
            log(f"  [5e] Buttons: {fail_buttons}")
            log(f"  [5e] Inputs: {fail_inputs}")
            log(f"  [5e] Errors: {fail_errors}")
            log(f"  [5e] Text: {fail_text[:500]}")
            cancel_number(act_id)
            save_record({
                "phone": f"+{phone}",
                "password": password,
                "phase": 1,
                "status": "password_submit_failed",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
            })
            return {"phone": phone, "password": password, "act_id": act_id, "reg_failed": True, "status": "password_submit_failed", "recorded": True}

        # Wait for SMS (non-blocking via asyncio.to_thread)
        log("  [6] Waiting for SMS...")
        sms_code = await asyncio.to_thread(get_sms, act_id, 120)

        if not sms_code:
            log("  SMS timeout, marking failed without retry.")
            cancel_number(act_id)
            save_record({
                "phone": f"+{phone}",
                "password": password,
                "phase": 1,
                "status": "sms_failed",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
            })
            log(f"  [log] SMS failure recorded")
            return {"phone": phone, "password": password, "act_id": act_id, "reg_failed": True, "status": "sms_failed", "recorded": True}
        log(f"  [6] SMS code: {sms_code}")

        # Enter SMS code
        await cdp.focus_and_type('input', sms_code)
        await asyncio.sleep(0.3)
        await cdp.click_submit()
        await asyncio.sleep(8)
        url = await cdp.url()
        log(f"  [7] After SMS code: {url}")

        # Handle about-you page
        if "about-you" in (url or ""):
            log("  [8] Filling about-you...")
            about_title = await cdp.ev("document.title || ''")
            about_inputs = await cdp.ev("""Array.from(document.querySelectorAll('input')).map(function(i){
                return {
                    type: i.type || '',
                    name: i.name || '',
                    placeholder: i.placeholder || '',
                    value_len: (i.value || '').length
                };
            })""")
            about_buttons = await cdp.ev("""Array.from(document.querySelectorAll('button')).map(function(b){
                return {
                    text: b.textContent.trim().substring(0, 60),
                    disabled: !!b.disabled
                };
            })""")
            log(f"  [8a] Before about-you: url={url}, title={about_title}")
            log(f"  [8a] Inputs: {about_inputs}")
            log(f"  [8a] Buttons: {about_buttons}")
            first_names = ["Alex", "Sam", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Quinn"]
            name_ok = await cdp.focus_and_type('input[name="name"]', random.choice(first_names))
            await asyncio.sleep(0.3)
            has_age = await cdp.ev('!!document.querySelector(\'input[name="age"]\')')
            if has_age:
                age_ok = await cdp.focus_and_type('input[name="age"]', str(random.randint(22, 35)))
            else:
                age_ok = False
            name_len = await cdp.ev("document.querySelector('input[name=\"name\"]')?.value?.length || 0")
            age_len = await cdp.ev("document.querySelector('input[name=\"age\"]')?.value?.length || 0")
            log(f"  [8b] Filled about-you: name_ok={name_ok}, name_len={name_len}, has_age={has_age}, age_ok={age_ok}, age_len={age_len}")
            await asyncio.sleep(0.3)
            await cdp.click_submit()
            await asyncio.sleep(5)
            await cdp.ev("""(function(){
                var btns = Array.from(document.querySelectorAll('button'));
                var c = btns.find(function(b){
                    var t = b.textContent.trim();
                    return t==='Confirm'||t==='纭畾';
                });
                if(c) c.click();
            })()""")
            await asyncio.sleep(3)
            await cdp.click_submit()
            await asyncio.sleep(10)
            url = await cdp.url()
            log(f"  [8] After about-you: {url}")

        # Check success
        if "chatgpt.com" in (url or "") and "auth" not in (url or ""):
            log("  鉁?Registration successful!")
            finish_number(act_id)
            return {"phone": phone, "password": password, "act_id": act_id}

        # Error recovery
        if "error" in (url or "") or "500" in (url or ""):
            log("  [!] Error page, checking if account was created...")
            await cdp.ev("window.location.href = 'https://chatgpt.com/'")
            await asyncio.sleep(8)
            url = await cdp.url()
            if "chatgpt.com" in (url or "") and "auth" not in (url or ""):
                log("  鉁?Account created despite error!")
                finish_number(act_id)
                return {"phone": phone, "password": password, "act_id": act_id}

        log(f"  鉁?Registration failed, final URL: {url}")
        cancel_number(act_id)
        return {"phone": phone, "password": password, "act_id": act_id, "reg_failed": True}


async def main():
    target_count = _args.count

    log("=" * 60)
    log(f"  BATCH REGISTER ({target_count} accounts)")
    log(f"  Proxy: {'enabled' if use_proxy else 'disabled (direct)'}")
    log("=" * 60)

    success = 0
    failed = 0

    for i in range(1, target_count + 1):
        log(f"\n{'='*60}")
        log(f"  ACCOUNT {i}/{target_count}")
        log(f"{'='*60}")

        # Restart Chrome with fresh fingerprint for each account
        log("[Fingerprint] Restarting Chrome with new profile...")
        restart_chrome_with_fingerprint(use_proxy=use_proxy)
        await asyncio.sleep(3)

        # Register
        result = await register_account()

        if not result:
            failed += 1
            log(f"  Registration failed (no number bought). Success: {success}, Failed: {failed}")
            save_record({
                "phase": 1,
                "status": "buy_number_failed",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
            })
            log(f"  [log] Buy number failure recorded")
            delay = random.randint(10, 30)
            log(f"  Waiting {delay}s before next attempt...")
            await asyncio.sleep(delay)
            continue

        phone = result["phone"]
        password = result["password"]

        if result.get("reg_failed"):
            failed += 1
            status = result.get("status", "reg_failed")
            if result.get("recorded"):
                log(f"  [log] Phase 1 failure already recorded as {status}. Total: {success} success, {failed} failed")
            else:
                save_record({
                    "phone": f"+{phone}",
                    "password": password,
                    "phase": 1,
                    "status": status,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
                })
                log(f"  [log] Phase 1 failure recorded as {status}. Total: {success} success, {failed} failed")
            delay = random.randint(10, 30)
            log(f"  Waiting {delay}s before next attempt...")
            await asyncio.sleep(delay)
            continue

        # Registration successful - save record
        save_record({
            "phone": f"+{phone}",
            "password": password,
            "phase": 1,
            "status": "registered",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
        })
        success += 1
        log(f"  鉁?Registered! Total: {success} success, {failed} failed")

        # Random delay between accounts
        delay = random.randint(15, 45)
        log(f"  Waiting {delay}s before next account...")
        await asyncio.sleep(delay)

    summary = {"success": success, "failed": failed, "total": target_count}
    log(f"\n{'='*60}")
    log(f"  FINAL: {success} registered, {failed} failed out of {target_count}")
    log(f"{'='*60}")
    print(f"__SUMMARY_JSON__{json.dumps(summary)}")

if __name__ == "__main__":
    asyncio.run(main())
