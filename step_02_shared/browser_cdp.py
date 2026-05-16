#!/usr/bin/env python3
"""
CDP browser automation class and Chrome restart with fingerprint.
"""
import json, asyncio, time, random, subprocess
from step_01_config.config import CDP_PORT, CHROME_PROFILE_DIR, WINDOW_SIZES, USER_AGENTS, TIMEZONES, LANGUAGES
from step_02_shared.records import log


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self.mid = 0

    async def send(self, method, params=None, timeout=15):
        self.mid += 1
        mid = self.mid
        cmd = {"id": mid, "method": method}
        if params:
            cmd["params"] = params
        await self.ws.send(json.dumps(cmd))
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=min(3, timeout-(time.time()-t0)))
                r = json.loads(raw)
                if r.get("id") == mid:
                    return r
            except asyncio.TimeoutError:
                continue
        return None

    async def ev(self, expr, timeout=10):
        r = await self.send("Runtime.evaluate",
            {"expression": expr, "returnByValue": True}, timeout=timeout)
        if r and "result" in r:
            res = r["result"].get("result", {})
            if "exceptionDetails" in r.get("result", {}):
                return None
            return res.get("value")
        return None

    async def url(self):
        return await self.ev("location.href")

    async def text(self, max_len=500):
        return await self.ev(f"document.body.innerText.substring(0, {max_len})")

    async def type_text(self, text):
        await self.send("Input.insertText", {"text": text})
        await asyncio.sleep(0.3)

    async def type_password(self, password):
        """Type password char-by-char using keyboard events (React-compatible)"""
        await self.ev("var el=document.querySelector('input[type=\"password\"]:not([style*=\"display:none\"])'); if(el){el.focus(); el.click();}")
        await asyncio.sleep(0.3)
        for ch in password:
            await self.send("Input.dispatchKeyEvent", {
                "type": "keyDown", "text": ch, "key": ch,
                "code": "", "windowsVirtualKeyCode": ord(ch)
            })
            await self.send("Input.dispatchKeyEvent", {
                "type": "keyUp", "key": ch,
                "code": "", "windowsVirtualKeyCode": ord(ch)
            })
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.3)
        pwd_len = await self.ev("document.querySelector('input[type=\"password\"]:not([style*=\"display:none\"])')?.value?.length || 0")
        return pwd_len

    async def focus_and_type(self, selector, text):
        await self.ev(f"""(function(){{
            var el = document.querySelector('{selector}');
            if(el) {{ el.focus(); el.value='';
            el.dispatchEvent(new Event('input', {{bubbles:true}})); }}
        }})()""")
        await asyncio.sleep(0.2)
        doc = await self.send("DOM.getDocument", {"depth": 1})
        if not doc or "result" not in doc:
            return False
        root = doc["result"]["root"]["nodeId"]
        inp = await self.send("DOM.querySelector", {"nodeId": root, "selector": selector})
        if not inp or not inp.get("result", {}).get("nodeId"):
            return False
        nid = inp["result"]["nodeId"]
        await self.send("DOM.focus", {"nodeId": nid})
        await asyncio.sleep(0.1)
        await self.type_text(text)
        return True

    async def click_submit(self):
        await self.ev("""(function(){
            var btn = document.querySelector('button[type="submit"]');
            if(!btn) btn = Array.from(document.querySelectorAll('button')).find(function(b){
                var t = b.textContent.trim();
                return t === 'Continue' || t === '继续' || /finish creating account/i.test(t);
            });
            if(btn) btn.click();
        })()""")

    async def click_text(self, text):
        await self.ev(f"""(function(){{
            var all = Array.from(document.querySelectorAll('button, a, span, div'));
            var el = all.find(function(e){{ return e.textContent.trim().includes('{text}'); }});
            if(el) el.click();
        }})()""")

    async def inject_fingerprint(self):
        """Inject fingerprint overrides to avoid detection"""
        tz = random.choice(TIMEZONES)
        lang = random.choice(LANGUAGES)
        await self.ev(f"""(function(){{
            // Override timezone
            var DateOrig = Date;
            // Override navigator properties
            Object.defineProperty(navigator, 'webdriver', {{get: function(){{ return false; }}}});
            Object.defineProperty(navigator, 'languages', {{get: function(){{ return '{lang}'.split(',').map(function(l){{return l.split(';')[0]}}); }}}});
            // Override plugins to look real
            Object.defineProperty(navigator, 'plugins', {{get: function(){{ return [1,2,3,4,5]; }}}});
            // Canvas noise
            var origToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function(type){{
                var ctx = this.getContext('2d');
                if(ctx) {{
                    var imgData = ctx.getImageData(0, 0, Math.min(this.width,2), Math.min(this.height,2));
                    imgData.data[0] = imgData.data[0] ^ {random.randint(1,3)};
                    ctx.putImageData(imgData, 0, 0);
                }}
                return origToDataURL.apply(this, arguments);
            }};
        }})()""")


def restart_chrome_with_fingerprint(use_proxy=False):
    """Kill Chrome and restart with randomized fingerprint (runs on OC24 locally)

    Args:
        use_proxy: Kept for caller compatibility; proxy mode is disabled.
    """
    _ = use_proxy
    w, h = random.choice(WINDOW_SIZES)
    ua = random.choice(USER_AGENTS)

    lines = []
    lines.append("#!/bin/bash")
    lines.append("export DISPLAY=:99")
    lines.append(f"pkill -f 'chromium.*--remote-debugging-port={CDP_PORT}' 2>/dev/null")
    lines.append("sleep 2")
    lines.append(f"rm -rf '{CHROME_PROFILE_DIR}'")
    chrome = "/snap/bin/chromium"
    chrome += f" --remote-debugging-port={CDP_PORT}"
    chrome += f" --user-data-dir='{CHROME_PROFILE_DIR}'"
    chrome += " --no-first-run --no-default-browser-check"
    chrome += " --disable-background-networking --disable-sync"
    chrome += f" --disable-extensions --window-size={w},{h}"
    chrome += " --no-sandbox --disable-gpu"
    chrome += " --disable-save-password-bubble --disable-infobars"
    chrome += " --hide-crash-restore-bubble --disable-session-crashed-bubble"
    chrome += " --disable-features=PasswordManager"
    chrome += " --disable-popup-blocking --password-store=basic"
    chrome += f" --user-agent='{ua}'"
    chrome += " 'about:blank' > /dev/null 2>" + chr(38) + "1 " + chr(38)
    lines.append(chrome)
    lines.append("CPID=$!")
    lines.append("echo Chrome_PID:$CPID")
    lines.append("sleep 6")
    lines.append(f"curl -sS http://127.0.0.1:{CDP_PORT}/json/version 2>/dev/null && echo CDP_SUCCESS || echo CDP_FAIL")

    script_content = chr(10).join(lines) + chr(10)
    launch_script = f"/tmp/launch_chrome_fp_{CDP_PORT}.sh"
    with open(launch_script, "w") as f:
        f.write(script_content)

    r = subprocess.run(["bash", launch_script],
        capture_output=True, text=True, timeout=30)
    ok = "CDP_SUCCESS" in r.stdout
    log(f"  Chrome worker: port={CDP_PORT}, profile={CHROME_PROFILE_DIR}")
    proxy_mode = "直连"
    log(f"  Chrome 已重启：{w}x{h}，UA: ...{ua[-30:]}，模式={proxy_mode}，CDP: {'正常' if ok else '失败'}")
    if not ok:
        log(f"  标准输出: {r.stdout[:200]}")
    return ok
