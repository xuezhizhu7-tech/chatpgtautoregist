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
                log(f"  [!] {name} price ${country_price} > ${MAX_PRICE}, skipping")
                continue
        except Exception:
            log(f"  [!] Failed to check price for {name}, skipping")
            continue

        r = subprocess.run(["curl", "-sS", "--max-time", "15",
            f"{HEROSMS}?api_key={HEROSMS_KEY}&action=getNumber&service={SERVICE}&country={hero_id}&maxPrice={MAX_PRICE}"],
            capture_output=True, text=True)
        if "ACCESS_NUMBER" in r.stdout:
            parts = r.stdout.split(":")
            act_id = parts[1]
            phone = parts[2]
            updated_cfg = {"id": hero_id, "dial": dial, "iso": iso, "name": name}
            log(f"  Number from {name} (${country_price:.3f})")
            return act_id, phone, updated_cfg

    log(f"  No numbers available from any country")
    return None, None, country_cfg


def cancel_number(act_id):
    subprocess.run(["curl", "-sS", "--max-time", "10",
        f"{HEROSMS}?api_key={HEROSMS_KEY}&action=setStatus&id={act_id}&status=8"],
        capture_output=True, text=True)


def finish_number(act_id):
    subprocess.run(["curl", "-sS", "--max-time", "10",
        f"{HEROSMS}?api_key={HEROSMS_KEY}&action=setStatus&id={act_id}&status=6"],
        capture_output=True, text=True)


def get_sms(act_id, timeout=150):
    """Poll for SMS code (blocking). Use asyncio.to_thread() from async callers."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = subprocess.run(["curl", "-sS", "--max-time", "10",
            f"{HEROSMS}?api_key={HEROSMS_KEY}&action=getStatus&id={act_id}"],
            capture_output=True, text=True)
        if "STATUS_OK" in r.stdout:
            return r.stdout.split(":")[1]
        if "STATUS_CANCEL" in r.stdout:
            return None
        time.sleep(10)
    log(f"  [SMS] Timeout after {timeout}s, cancelling number {act_id}")
    cancel_number(act_id)
    return None
