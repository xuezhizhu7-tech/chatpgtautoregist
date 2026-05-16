#!/usr/bin/env python3
"""
Auto-monitor SMS stock and batch register when available.
- Checks stock every 5 minutes
- Runs N accounts per batch, verifies no phone waste
- Runs batches through the local network directly
"""
import subprocess, json, time, os, sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from step_01_config.config import (
    HEROSMS_KEY, HEROSMS, SERVICE, MAX_PRICE,
    MONITOR_COUNTRIES as COUNTRIES,
    BATCH_SIZE,
    SCRIPT, LOG_DIR, STATE_FILE,
)

os.makedirs(LOG_DIR, exist_ok=True)


def log(msg):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"total_success": 0, "total_failed": 0, "total_wasted_numbers": 0}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def check_stock_country(country_id):
    """Check OpenAI SMS stock for a specific country"""
    try:
        r = subprocess.run(["curl", "-sS", "--max-time", "10",
            f"{HEROSMS}?api_key={HEROSMS_KEY}&action=getPrices&service={SERVICE}&country={country_id}"],
            capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        info = data.get(str(country_id), {}).get(SERVICE, {})
        return int(info.get("count", 0)), int(info.get("physicalCount", 0)), float(info.get("cost", 0))
    except Exception:
        return 0, 0, 0


def check_stock():
    """Check all countries, return first with stock: (country_info, count, physical, price)"""
    for c in COUNTRIES:
        count, physical, price = check_stock_country(c["id"])
        if count > 0 and price <= MAX_PRICE:
            return c, count, physical, price
    return None, 0, 0, 0


def run_batch(batch_size, country_info=None):
    """Run a batch of registrations, return (success, failed, wasted_numbers)"""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    logfile = f"{LOG_DIR}/batch_{ts}.log"

    env = os.environ.copy()
    env["DISPLAY"] = ":99"

    # Build command with country flags. Proxy mode is disabled for stability.
    cmd = ["python3", "-u", SCRIPT, str(batch_size)]
    if country_info:
        cmd += ["--country", str(country_info["id"]), "--dial", country_info["dial"], "--iso", country_info["iso"]]
    cmd += ["--no-proxy"]

    country_name = country_info["name"] if country_info else "default"
    log(f"  Running batch of {batch_size} ({country_name})...")
    r = subprocess.run(
        cmd,
        capture_output=True, text=True, env=env, timeout=1800
    )

    output = r.stdout
    stderr = r.stderr
    returncode = r.returncode

    with open(logfile, "w") as f:
        f.write(output)
        if stderr:
            f.write("\n--- STDERR ---\n")
            f.write(stderr)
        f.write(f"\n--- EXIT CODE: {returncode} ---\n")

    # Parse results: prefer structured JSON summary from child process
    success = 0
    failed = 0
    summary_parsed = False

    for line in reversed(output.split("\n")):
        if "__SUMMARY_JSON__" in line:
            try:
                payload = line.split("__SUMMARY_JSON__", 1)[1].strip()
                data = json.loads(payload)
                success = int(data.get("success", 0))
                failed = int(data.get("failed", 0))
                summary_parsed = True
            except Exception:
                pass
            break

    if not summary_parsed:
        # Fallback: parse human-readable FINAL line
        for line in output.split("\n"):
            if "FINAL:" in line:
                import re
                m = re.search(r"(\d+)\s+\w+,\s+(\d+)\s+failed", line)
                if m:
                    success = int(m.group(1))
                    failed = int(m.group(2))

    # If child crashed, log the details
    if returncode != 0:
        log(f"  ⚠ Child exited with code {returncode}")
        if stderr:
            for line in stderr.strip().split("\n")[-5:]:
                log(f"    stderr: {line}")

    # Check for wasted numbers
    sms_received = output.count("[6] SMS code:")
    registrations_ok = output.count("✓ Registration successful!")
    wasted = sms_received - registrations_ok

    log(f"  Result: {success} registered, {failed} failed, {wasted} wasted numbers")
    log(f"  Log: {logfile}")

    return success, failed, wasted


def main():
    log("=" * 50)
    log("AUTO BATCH REGISTER - SMS Monitor")
    log("=" * 50)

    state = load_state()
    log(f"State: total_success={state['total_success']}, total_failed={state['total_failed']}")

    consecutive_no_stock = 0

    while True:
        # Check stock across all countries
        active_country, count, physical, price = check_stock()

        if active_country is None or count == 0:
            consecutive_no_stock += 1
            # Adaptive wait: 5min normally, 15min after many checks
            wait = 300 if consecutive_no_stock < 12 else 900
            log(f"No stock (check #{consecutive_no_stock}). Next check in {wait//60}min...")
            time.sleep(wait)
            continue

        consecutive_no_stock = 0
        log(f"✓ Stock reported: {active_country['name']} count={count}, physical={physical}, price=${price}")

        # Verify by actually trying to buy a number
        try:
            r = subprocess.run(["curl", "-sS", "--max-time", "10",
                f"{HEROSMS}?api_key={HEROSMS_KEY}&action=getNumber&service={SERVICE}&country={active_country['id']}"],
                capture_output=True, text=True, timeout=15)
            resp = r.stdout.strip()
            if "NO_NUMBERS" in resp:
                log(f"  But getNumber returned NO_NUMBERS. Fake stock, waiting...")
                time.sleep(300)
                continue
            elif "ACCESS_NUMBER" in resp:
                # Got a number! Cancel it immediately (we'll let the batch script buy its own)
                parts = resp.split(":")
                act_id = parts[1]
                subprocess.run(["curl", "-sS", "--max-time", "10",
                    f"{HEROSMS}?api_key={HEROSMS_KEY}&action=setStatus&id={act_id}&status=8"],
                    capture_output=True, text=True, timeout=15)
                log(f"  ✓ Verified: real stock available (test number cancelled)")
            else:
                log(f"  Unexpected response: {resp[:80]}, waiting...")
                time.sleep(300)
                continue
        except Exception as e:
            log(f"  Verify error: {e}, waiting...")
            time.sleep(300)
            continue

        log("  Proxy: DIRECT (local network)")

        # Run batch
        batch = min(BATCH_SIZE, count)
        try:
            success, failed, wasted = run_batch(batch, active_country)
        except subprocess.TimeoutExpired:
            log("  ⚠ Batch timed out (30min). Continuing...")
            success, failed, wasted = 0, batch, 0
        except Exception as e:
            log(f"  ⚠ Batch error: {e}. Continuing...")
            success, failed, wasted = 0, batch, 0

        # Update state
        state["total_success"] += success
        state["total_failed"] += failed
        state["total_wasted_numbers"] += wasted
        save_state(state)

        # Report
        log(f"  TOTAL: {state['total_success']} success, {state['total_failed']} failed, {state['total_wasted_numbers']} wasted")

        # If wasted numbers detected, STOP and alert
        if wasted > 0:
            log("⚠️  WASTED NUMBERS DETECTED! Stopping for review.")
            break

        # If all failed (likely stock ran out mid-batch), wait before retry
        if success == 0 and failed > 0:
            log("  All failed, waiting 5min before retry...")
            time.sleep(300)
        else:
            # Brief pause between batches
            log("  Waiting 30s before next batch...")
            time.sleep(30)


if __name__ == "__main__":
    main()
