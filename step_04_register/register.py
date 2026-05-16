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
_parser.add_argument("--no-proxy", action="store_true", help="Ignored; proxy mode is disabled")
_args, _ = _parser.parse_known_args()

# Build country config from overrides (returns dict, no mutable globals)
country_cfg = apply_country_override(
    country_id=_args.country,
    dial=_args.dial,
    iso=_args.iso,
)
use_proxy = False


def random_password():
    return DEFAULT_PASSWORD


async def register_account():
    """Register new account with phone number. Returns dict or None."""
    act_id, phone, country_cfg = buy_number()
    if not act_id:
        log("  ✗ 购买号码失败")
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
        log(f"  [1] 已打开页面: {url}")

        # Wait for page to fully load
        for wait_i in range(15):
            title = await cdp.ev("document.title || ''")
            body_len = await cdp.ev("document.body ? document.body.innerText.length : 0")
            if wait_i == 0 or wait_i == 5:
                snip = await cdp.ev("document.body ? document.body.innerText.substring(0,100) : ''")
                log(f"    [等待 {wait_i}] 标题={title} 正文长度={body_len} 文本={str(snip)[:80]}")
            if title and "moment" not in title.lower() and "just" not in title.lower() and body_len and body_len > 20:
                break
            await asyncio.sleep(5)

        # Handle "Unable to load site" / VPN error
        body_text = await cdp.ev("document.body ? document.body.innerText.substring(0,200) : ''")
        if "unable to load" in (body_text or "").lower() or "vpn" in (body_text or "").lower():
            log("  [!] 网站加载受阻，正在重试...")
            await cdp.ev("location.reload()")
            await asyncio.sleep(8)
            body_text = await cdp.ev("document.body ? document.body.innerText.substring(0,200) : ''")
            if "unable to load" in (body_text or "").lower():
                log("  ✗ 重试后网站仍然加载受阻")
                cancel_number(act_id, country_cfg.get("bought_at"))
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
            log("  [2] 检测到内嵌认证界面")
            phone_clicked = await cdp.ev("""(function(){
                var btns = Array.from(document.querySelectorAll('button'));
                var p = btns.find(function(b){ return /phone/i.test(b.textContent); });
                if(p) { p.click(); return true; }
                return false;
            })()""")
            if not phone_clicked:
                log("    先点击“更多选项”...")
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
            log("  [2] 检测到旧版界面，正在点击注册...")
            clicked = await cdp.ev("""(function(){
                var els = Array.from(document.querySelectorAll("a, button, [role=button]"));
                var el = els.find(function(e) { return /sign up/i.test(e.textContent); });
                if(el) { el.click(); return true; }
                return false;
            })()""")
            if not clicked:
                log("  [!] 未找到注册按钮，尝试直接打开注册地址...")
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
                    log(f"  [!] 当前不在认证页面: {url}，尝试直接打开注册地址...")
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
            log("  [!] 未找到手机号输入框，尝试直接打开手机号注册地址...")
            await cdp.ev("window.location.href = 'https://auth.openai.com/log-in-or-create-account?usernameKind=phone_number'")
            await asyncio.sleep(8)
            await cdp.inject_fingerprint()
            has_tel = await cdp.ev("!!document.querySelector(\"input[type='tel']\")")
            if not has_tel:
                url = await cdp.url()
                body = await cdp.ev("document.body ? document.body.innerText.substring(0,200) : ''")
                log(f"  ✗ 无法进入手机号输入页。URL: {url}")
                log(f"    页面正文: {body[:100]}")
                cancel_number(act_id, country_cfg.get("bought_at"))
                save_record({
                    "phone": f"+{phone}" if phone else None,
                    "password": password,
                    "phase": 1,
                    "status": "no_phone_input",
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
                })
                return None

        url = await cdp.url()
        log(f"  [2] 已准备输入手机号: {url}")

        # Input phone number
        full_phone = f"+{phone}"
        await cdp.focus_and_type('input[type="tel"]', full_phone)
        await asyncio.sleep(1)

        # Click Continue
        await cdp.click_submit()
        await asyncio.sleep(8)
        url = await cdp.url()
        log(f"  [4] 提交手机号后: {url}")

        # Check if number already registered
        if "log-in/password" in (url or ""):
            log("  [!] 该号码已注册，标记失败且不重试。")
            cancel_number(act_id, country_cfg.get("bought_at"))
            save_record({
                "phone": f"+{phone}",
                "password": password,
                "phase": 1,
                "status": "already_registered",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
            })
            log("  [日志] 已记录号码已注册状态")
            return {"phone": phone, "password": password, "act_id": act_id, "reg_failed": True, "status": "already_registered", "recorded": True}

        # Should be on create-account/password page
        if "password" not in (url or ""):
            await asyncio.sleep(4)
            url = await cdp.url()
            log(f"  [4b] 重新检查: {url}")

        if "password" not in (url or ""):
            log(f"  ✗ 页面状态异常: {url}")
            cancel_number(act_id, country_cfg.get("bought_at"))
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
        log(f"  [5] 已逐字符输入密码，长度={pwd_len}")
        if not pwd_len or pwd_len == 0:
            log("  [5] 警告：输入后密码框仍为空！")

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
                log(f"  [5r] 检测到超时/错误（第 {retry_i+1}/3 次），正在点击重试...")
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
                log("  [5r] 仍停留在密码页，重新提交...")
                await cdp.click_submit()
                await asyncio.sleep(10)
                url = await cdp.url()
            else:
                break

        log(f"  [5] 提交密码后: {url}")

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
            log("  多次重试后密码提交失败")
            log(f"  [5e] url={url}, 标题={fail_title}, 密码长度={pwd_len_final}")
            log(f"  [5e] 按钮: {fail_buttons}")
            log(f"  [5e] 输入框: {fail_inputs}")
            log(f"  [5e] 错误信息: {fail_errors}")
            log(f"  [5e] 文本: {fail_text[:500]}")
            failure_text = (fail_text or "").lower()
            failure_errors_text = " ".join(fail_errors or []).lower()
            if "account for this phone number already exists" in failure_text or "account for this phone number already exists" in failure_errors_text:
                failure_status = "already_registered"
                log("  [5e] 检测到该手机号已有账号")
            else:
                failure_status = "password_submit_failed"
            cancel_number(act_id, country_cfg.get("bought_at"))
            save_record({
                "phone": f"+{phone}",
                "password": password,
                "phase": 1,
                "status": failure_status,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
            })
            return {"phone": phone, "password": password, "act_id": act_id, "reg_failed": True, "status": failure_status, "recorded": True}

        # Wait for SMS (non-blocking via asyncio.to_thread)
        log("  [6] 正在等待短信验证码...")
        sms_code = await asyncio.to_thread(get_sms, act_id, 120, country_cfg.get("bought_at"))

        if not sms_code:
            log("  短信等待超时，标记失败且不重试。")
            log("  [短信] 超时后再次确认取消号码...")
            cancel_number(act_id, country_cfg.get("bought_at"))
            save_record({
                "phone": f"+{phone}",
                "password": password,
                "phase": 1,
                "status": "sms_failed",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
            })
            log(f"  [日志] 已记录短信失败")
            return {"phone": phone, "password": password, "act_id": act_id, "reg_failed": True, "status": "sms_failed", "recorded": True}
        log(f"  [6] SMS code: {sms_code}")

        # Enter SMS code
        await cdp.focus_and_type('input', sms_code)
        await asyncio.sleep(0.3)
        await cdp.click_submit()
        await asyncio.sleep(8)
        url = await cdp.url()
        log(f"  [7] 提交短信验证码后: {url}")

        # Handle about-you page
        if "about-you" in (url or ""):
            log("  [8] 正在填写个人信息页...")
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
            log(f"  [8a] 填写前: url={url}, 标题={about_title}")
            log(f"  [8a] 输入框: {about_inputs}")
            log(f"  [8a] 按钮: {about_buttons}")
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
            log(f"  [8b] 已填写个人信息: name_ok={name_ok}, name_len={name_len}, has_age={has_age}, age_ok={age_ok}, age_len={age_len}")
            await asyncio.sleep(0.3)

            # Check all consent checkboxes (React requires click() to sync state)
            # 1) Click "allCheckboxes" first so it propagates to individual consents
            # 2) Only click visible & enabled checkboxes; skip hidden/disabled
            checked_count = await cdp.ev("""(function(){
                var count = 0;
                // Try clicking the "select all" checkbox first
                var allCb = document.querySelector('input[name="allCheckboxes"]');
                if(allCb && !allCb.checked && !allCb.disabled && allCb.offsetParent !== null){
                    allCb.click();
                    count++;
                }
                // Then ensure every visible+enabled checkbox is checked
                var boxes = document.querySelectorAll('input[type="checkbox"]');
                boxes.forEach(function(cb){
                    if(!cb.checked && !cb.disabled && cb.offsetParent !== null){
                        cb.click();
                        count++;
                    }
                });
                return count;
            })()""")
            await asyncio.sleep(0.5)
            all_checked = await cdp.ev("""Array.from(document.querySelectorAll('input[type="checkbox"]')).filter(function(cb){ return !cb.disabled && cb.offsetParent !== null; }).every(function(cb){ return cb.checked; })""")
            log(f"  [8c] 复选框: 已点击 {checked_count} 个，是否全部选中={all_checked}")
            await asyncio.sleep(0.3)

            # Click "Finish creating account" button
            btn_clicked = await cdp.ev("""(function(){
                var btns = Array.from(document.querySelectorAll('button'));
                var btn = btns.find(function(b){
                    var t = b.textContent.trim();
                    return /finish creating account/i.test(t);
                });
                if(!btn) btn = document.querySelector('button[type="submit"]');
                if(btn && !btn.disabled){ btn.click(); return btn.textContent.trim(); }
                if(btn && btn.disabled) return 'disabled:' + btn.textContent.trim();
                return null;
            })()""")
            log(f"  [8c] 已点击按钮: {btn_clicked}")
            await asyncio.sleep(10)
            url = await cdp.url()
            log(f"  [8] 提交个人信息后: {url}")

            # Diagnose: if still on about-you, log page state for debugging
            if "about-you" in (url or ""):
                diag = await cdp.ev("""(function(){
                    var inputs = Array.from(document.querySelectorAll('input')).map(function(i){
                        return {name:i.name, type:i.type, checked:i.checked, disabled:i.disabled, value_len:(i.value||'').length};
                    });
                    var errors = Array.from(document.querySelectorAll('[role="alert"],.error,.field-error,.form-error')).map(function(e){ return e.textContent.trim(); });
                    var buttons = Array.from(document.querySelectorAll('button')).map(function(b){
                        return {text:b.textContent.trim(), disabled:b.disabled};
                    });
                    return JSON.stringify({inputs:inputs, errors:errors, buttons:buttons});
                })()""")
                log(f"  [8e] 仍停留在个人信息页，诊断信息: {diag}")

        # Check success
        if "chatgpt.com" in (url or "") and "auth" not in (url or ""):
            log("  ✓ Registration successful!")
            finish_number(act_id)
            return {"phone": phone, "password": password, "act_id": act_id}

        # Error recovery
        if "error" in (url or "") or "500" in (url or ""):
            log("  [!] 进入错误页面，正在检查账号是否已创建...")
            await cdp.ev("window.location.href = 'https://chatgpt.com/'")
            await asyncio.sleep(8)
            url = await cdp.url()
            if "chatgpt.com" in (url or "") and "auth" not in (url or ""):
                log("  ✓ 虽然出现错误页，但账号已创建！")
                finish_number(act_id)
                return {"phone": phone, "password": password, "act_id": act_id}

        # Classify failure
        fail_reason = "reg_failed"
        if "about-you" in (url or ""):
            fail_reason = "about_you_failed"
        elif "verify" in (url or ""):
            fail_reason = "verify_failed"

        log(f"  ✗ 注册失败（{fail_reason}），最终 URL: {url}")
        cancel_number(act_id, country_cfg.get("bought_at"))
        return {"phone": phone, "password": password, "act_id": act_id, "reg_failed": True, "status": fail_reason}


async def main():
    target_count = _args.count

    log("=" * 60)
    log(f"  批量注册（{target_count} 个账号）")
    log(f"  代理: {'已启用' if use_proxy else '已禁用（直连）'}")
    log("=" * 60)

    success = 0
    failed = 0

    for i in range(1, target_count + 1):
        log(f"\n{'='*60}")
        log(f"  账号 {i}/{target_count}")
        log(f"{'='*60}")

        # Restart Chrome with fresh fingerprint for each account
        log("[指纹] 正在使用新配置重启 Chrome...")
        restart_chrome_with_fingerprint(use_proxy=use_proxy)
        await asyncio.sleep(3)

        # Register
        result = await register_account()

        if not result:
            failed += 1
            log(f"  注册失败（未买到号码）。成功: {success}，失败: {failed}")
            save_record({
                "phase": 1,
                "status": "buy_number_failed",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
            })
            log(f"  [日志] 已记录购买号码失败")
            delay = random.randint(10, 30)
            log(f"  等待 {delay} 秒后进行下一次尝试...")
            await asyncio.sleep(delay)
            continue

        phone = result["phone"]
        password = result["password"]

        if result.get("reg_failed"):
            failed += 1
            status = result.get("status", "reg_failed")
            if result.get("recorded"):
                log(f"  [日志] 阶段 1 失败已记录为 {status}。累计: 成功 {success}，失败 {failed}")
            else:
                save_record({
                    "phone": f"+{phone}",
                    "password": password,
                    "phase": 1,
                    "status": status,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
                })
                log(f"  [日志] 阶段 1 失败已记录为 {status}。累计: 成功 {success}，失败 {failed}")
            delay = random.randint(10, 30)
            log(f"  等待 {delay} 秒后进行下一次尝试...")
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
        log(f"  ✓ Registered! Total: {success} success, {failed} failed")

        # Random delay between accounts
        delay = random.randint(15, 45)
        log(f"  等待 {delay} 秒后处理下一个账号...")
        await asyncio.sleep(delay)

    summary = {"success": success, "failed": failed, "total": target_count}
    log(f"\n{'='*60}")
    log(f"  FINAL: {success} registered, {failed} failed out of {target_count}")
    log(f"{'='*60}")
    print(f"__SUMMARY_JSON__{json.dumps(summary)}")

if __name__ == "__main__":
    asyncio.run(main())
