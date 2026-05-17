#!/usr/bin/env python3
"""
Monitor HeroSMS stock and query phone numbers only.

This script no longer starts registration batches or buys phone numbers. It
only checks configured countries and prints available stock.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from step_01_config import local_secrets
except ImportError:
    local_secrets = None


def _env(key, default=""):
    if key in os.environ:
        return os.environ[key]
    if local_secrets and hasattr(local_secrets, key):
        return getattr(local_secrets, key)
    return default


def _env_int(key, default):
    return int(_env(key, str(default)))


def _env_float(key, default):
    return float(_env(key, str(default)))


def _required_env(key):
    value = _env(key, "")
    if not value:
        raise RuntimeError(
            f"Missing required secret: {key} "
            "(set it in step_01_config/local_secrets.py or environment)"
        )
    return value


HEROSMS_KEY = _required_env("HEROSMS_KEY")
HEROSMS = _env("HEROSMS", "https://hero-sms.com/stubs/handler_api.php")
SERVICE = _env("HEROSMS_SERVICE", "dr")
MAX_PRICE = _env_float("HEROSMS_MAX_PRICE", 0.03)
CHECK_INTERVAL = _env_int("MONITOR_CHECK_INTERVAL", 300)

COUNTRIES = [
    {"id": 151, "name": "Chile", "dial": "56", "iso": "CL"},
    {"id": 16, "name": "UK", "dial": "44", "iso": "GB"},
]


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def api_call(params, timeout=15):
    query = "&".join(f"{key}={value}" for key, value in params.items())
    result = subprocess.run(
        ["curl", "-sS", "--max-time", "10", f"{HEROSMS}?{query}"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout.strip()


def check_stock_country(country_id):
    """Return (count, physical_count, price) for one country."""
    try:
        resp = api_call(
            {
                "api_key": HEROSMS_KEY,
                "action": "getPrices",
                "service": SERVICE,
                "country": country_id,
            }
        )
        data = json.loads(resp)
        info = data.get(str(country_id), {}).get(SERVICE, {})
        return (
            int(info.get("count", 0)),
            int(info.get("physicalCount", 0)),
            float(info.get("cost", 0)),
        )
    except Exception as exc:
        log(f"Failed to check stock for country {country_id}: {exc}")
        return 0, 0, 0


def check_stock():
    """Return first country with available stock within MAX_PRICE."""
    for country in COUNTRIES:
        count, physical, price = check_stock_country(country["id"])
        log(
            f"{country['name']}: count={count}, "
            f"physical={physical}, price=${price:.4f}"
        )
        if count > 0 and price <= MAX_PRICE:
            return country, count, physical, price
    return None, 0, 0, 0


def run_once():
    country, count, physical, price = check_stock()
    if country is None:
        log("No available phone number")
        return False

    log(
        f"Stock available: {country['name']} "
        f"count={count}, physical={physical}, price=${price:.4f}"
    )
    return True


def main():
    parser = argparse.ArgumentParser(description="Monitor HeroSMS phone stock only.")
    parser.add_argument("--once", action="store_true", help="Query once and exit")
    parser.add_argument(
        "--interval",
        type=int,
        default=CHECK_INTERVAL,
        help=f"Polling interval in seconds, default {CHECK_INTERVAL}",
    )
    args = parser.parse_args()

    log("=" * 50)
    log("Phone stock monitor")
    log("=" * 50)
    log(f"service={SERVICE}, max_price=${MAX_PRICE}, interval={args.interval}s")

    while True:
        found = run_once()
        if args.once:
            break
        wait = 30 if found else args.interval
        log(f"Query again in {wait} seconds...")
        time.sleep(wait)


if __name__ == "__main__":
    main()
