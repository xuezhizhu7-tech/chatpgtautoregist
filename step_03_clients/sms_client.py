#!/usr/bin/env python3
"""
HeroSMS client: buy/cancel/finish numbers, get SMS codes, country override.
buy_number() returns (act_id, phone, country_cfg) to avoid mutable global state.
"""
import subprocess, json, time
from step_01_config.config import HEROSMS_KEY, HEROSMS, SERVICE, MAX_PRICE, FALLBACK_COUNTRIES, DEFAULT_COUNTRY
from step_02_shared.records import log


def apply_country_override(country_id=None, dial=None, iso=None):
    """Return a country config dict instead of mutating globals.

    Returns: {"id": int, "dial": str, "iso": str, "name": str}
    """
    cfg = dict(DEFAULT_COUNTRY)
    if country_id is not None:
        cfg["id"] = country_id
    if dial is not None:
        cfg["dial"] = dial
    if iso is not None:
        cfg["iso"] = iso
    # Derive name from FALLBACK_COUNTRIES if possible
    for hid, d, i, n in FALLBACK_COUNTRIES:
        if hid == cfg["id"]:
            cfg["name"] = n
            break
    return cfg


def buy_number(country_cfg=None):
    """Try to buy a number from fallback countries in order.

    Args:
        country_cfg: optional starting country config (used for logging).

    Returns:
        (act_id, phone, country_cfg) on success, or (None, None, country_cfg) on failure.
        The returned country_cfg reflects the country that actually supplied the number.
    """
    if country_cfg is None:
        country_cfg = dict(DEFAULT_COUNTRY)

    for hero_id, dial, iso, name in FALLBACK_COUNTRIES:
        price_check = subprocess.run(["curl", "-sS", "--max-time", "10",
            f"{HEROSMS}?api_key={HEROSMS_KEY}&action=getPrices&service={SERVICE}&country={hero_id}"],
            capture_output=True, text=True)
        try:
            price_data = json.loads(price_check.stdout)
            country_price = float(
                price_data.get(str(hero_id), {}).get(SERVICE, {}).get("cost", 999)
            )
            if country_price > MAX_PRICE:
                log(f"  [!] {name} 价格 ${country_price} 超过 ${MAX_PRICE}，跳过")
                continue
        except Exception:
            log(f"  [!] 检查 {name} 价格失败，跳过")
            continue

        r = subprocess.run(["curl", "-sS", "--max-time", "15",
            f"{HEROSMS}?api_key={HEROSMS_KEY}&action=getNumber&service={SERVICE}&country={hero_id}&maxPrice={MAX_PRICE}"],
            capture_output=True, text=True)
        if "ACCESS_NUMBER" in r.stdout:
            parts = r.stdout.split(":")
            act_id = parts[1]
            phone = parts[2]
            updated_cfg = {"id": hero_id, "dial": dial, "iso": iso, "name": name, "bought_at": time.time()}
            log(f"  已从 {name} 获取号码（${country_price:.3f}）")
            return act_id, phone, updated_cfg

    log(f"  所有国家当前都没有可用号码")
    return None, None, country_cfg


def cancel_number(act_id, bought_at=None):
    log(f"  [短信] 正在取消号码 act_id={act_id}...")
    r = subprocess.run(["curl", "-sS", "--max-time", "10",
        f"{HEROSMS}?api_key={HEROSMS_KEY}&action=setStatus&id={act_id}&status=8"],
        capture_output=True, text=True)
    resp = r.stdout.strip()
    log(f"  [短信] 取消响应: {resp or '空响应'}")

    if "EARLY_CANCEL_DENIED" in resp:
        min_activation = 120
        try:
            data = json.loads(resp)
            min_activation = int(data.get("info", {}).get("minActivationTime", min_activation))
        except Exception:
            pass
        if bought_at:
            wait = max(0, min_activation - int(time.time() - bought_at) + 2)
        else:
            wait = min_activation + 2
        log(f"  [短信] 暂不允许提前取消；等待 {wait} 秒后重试...")
        remaining = wait
        while remaining > 0:
            if remaining <= 5:
                sleep_for = 1
            else:
                sleep_for = min(10, remaining - 5)
            log(f"  [短信] 取消重试倒计时: 剩余 {remaining} 秒")
            time.sleep(sleep_for)
            remaining -= sleep_for
        r = subprocess.run(["curl", "-sS", "--max-time", "10",
            f"{HEROSMS}?api_key={HEROSMS_KEY}&action=setStatus&id={act_id}&status=8"],
            capture_output=True, text=True)
        log(f"  [短信] 取消重试响应: {r.stdout.strip() or '空响应'}")


def finish_number(act_id):
    log(f"  [短信] 正在标记号码完成 act_id={act_id}...")
    r = subprocess.run(["curl", "-sS", "--max-time", "10",
        f"{HEROSMS}?api_key={HEROSMS_KEY}&action=setStatus&id={act_id}&status=6"],
        capture_output=True, text=True)
    log(f"  [短信] 完成响应: {r.stdout.strip() or '空响应'}")


def get_sms(act_id, timeout=150, bought_at=None):
    """Poll for SMS code (blocking). Use asyncio.to_thread() from async callers."""
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        r = subprocess.run(["curl", "-sS", "--max-time", "10",
            f"{HEROSMS}?api_key={HEROSMS_KEY}&action=getStatus&id={act_id}"],
            capture_output=True, text=True)
        status = r.stdout.strip()
        remaining = max(0, int(deadline - time.time()))
        if "STATUS_OK" in r.stdout:
            log(f"  [短信] 第 {attempt} 次查询：已收到验证码")
            return r.stdout.split(":")[1]
        if "STATUS_CANCEL" in r.stdout:
            log(f"  [短信] 第 {attempt} 次查询：服务商已取消")
            return None
        log(f"  [短信] 第 {attempt} 次查询：{status or '空响应'}；剩余 {remaining} 秒")
        time.sleep(10)
    log(f"  [短信] 等待 {timeout} 秒超时，正在取消号码 {act_id}")
    cancel_number(act_id, bought_at)
    return None
