#!/usr/bin/env python3
"""
Shared configuration for auto_batch_monitor, register, and oauth_import.
Secrets can be provided through step_01_config/local_secrets.py or environment variables.
"""
import os, re, subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from step_01_config import local_secrets
except ImportError:
    local_secrets = None


def _env(key, default=""):
    """Read from environment, fall back to default."""
    if key in os.environ:
        return os.environ[key]
    if local_secrets and hasattr(local_secrets, key):
        return getattr(local_secrets, key)
    return default


def _env_int(key, default):
    return int(os.environ.get(key, str(default)))


def _env_float(key, default):
    return float(os.environ.get(key, str(default)))


def _required_env(key):
    value = _env(key, "")
    if not value:
        raise RuntimeError(f"Missing required secret: {key} (set it in step_01_config/local_secrets.py or environment)")
    return value


# ============================================================
# HeroSMS API (shared)
# ============================================================
HEROSMS_KEY = _required_env("HEROSMS_KEY")
HEROSMS = _env("HEROSMS", "https://hero-sms.com/stubs/handler_api.php")
SERVICE = _env("HEROSMS_SERVICE", "dr")  # OpenAI
MAX_PRICE = _env_float("HEROSMS_MAX_PRICE", 0.03)

# ============================================================
# Country / Phone (shared)
# ============================================================
DEFAULT_COUNTRY = {
    "id": _env_int("DEFAULT_COUNTRY_ID", 151),
    "name": _env("DEFAULT_COUNTRY_NAME", "Chile"),
    "dial": _env("DEFAULT_COUNTRY_DIAL", "56"),
    "iso": _env("DEFAULT_COUNTRY_ISO", "CL"),
}

# Countries to monitor (auto_batch_monitor)
MONITOR_COUNTRIES = [
    {"id": 151, "name": "Chile", "dial": "56", "iso": "CL"},
    {"id": 16, "name": "UK", "dial": "44", "iso": "GB"},
    {"id": 4, "name": "Philippines", "dial": "63", "iso": "PH"},
    {"id": 73, "name": "India", "dial": "73", "iso": "IN"},
]

# Fallback countries for buying numbers (register.py)
# (hero_id, dial_code, iso, name) - preferred order
FALLBACK_COUNTRIES = [
    (151, "56", "CL", "Chile"),
    (16,  "44", "GB", "UK"),
    # Temporarily avoid Philippines: recent runs reached password submit but OpenAI returned
    # "Failed to create account. Please try again" for PH numbers.
    # (4,   "63", "PH", "Philippines"),
    (73,  "73", "IN", "India"),
]

# ============================================================
# Batch monitor
# ============================================================
BATCH_SIZE = _env_int("BATCH_SIZE", 5)

# ============================================================
# Sub2API (oauth_import.py)
# ============================================================
SUB2API = _env("SUB2API", "http://localhost:8080")
SUB2API_EMAIL = _required_env("SUB2API_EMAIL")
SUB2API_PASS = _required_env("SUB2API_PASS")

# ============================================================
# Email Providers (register.py / oauth_import.py)
# ============================================================
CLOUD_MAIL_URL = _env("CLOUD_MAIL_URL", "https://mail.catmaomi.shop")
CLOUD_MAIL_EMAIL = _required_env("CLOUD_MAIL_EMAIL")
CLOUD_MAIL_PASS = _required_env("CLOUD_MAIL_PASS")
EMAIL_DOMAIN = _required_env("EMAIL_DOMAIN")

GMAIL_USER = _env("GMAIL_USER", "")
GMAIL_PASS = _env("GMAIL_PASS", "")

# ============================================================
# Browser / CDP (register.py / oauth_import.py)
# ============================================================
CDP_PORT = _env_int("CDP_PORT", 9336)
CHROME_PROFILE_DIR = _env("CHROME_PROFILE_DIR", f"/tmp/chrome-reg-{CDP_PORT}")

BROWSER_OPTIONS = {
    "google-chrome-stable": {
        "path": "/usr/bin/google-chrome-stable",
        "process_pattern": "(chromium|chrome)",
    },
    "chromium-snap": {
        "path": "/snap/bin/chromium",
        "process_pattern": "(chromium|chrome)",
    },
}
BROWSER = _env("BROWSER", "google-chrome-stable")
if BROWSER not in BROWSER_OPTIONS:
    supported = ", ".join(sorted(BROWSER_OPTIONS))
    raise RuntimeError(f"Unsupported BROWSER={BROWSER!r}; supported values: {supported}")
BROWSER_PATH = _env("BROWSER_PATH", BROWSER_OPTIONS[BROWSER]["path"])
BROWSER_PROCESS_PATTERN = _env("BROWSER_PROCESS_PATTERN", BROWSER_OPTIONS[BROWSER]["process_pattern"])


def _detect_browser_version(browser_path):
    try:
        r = subprocess.run([browser_path, "--version"], capture_output=True, text=True, timeout=5)
    except Exception:
        return ""
    text = (r.stdout or r.stderr or "").strip()
    m = re.search(r"(\d+\.\d+\.\d+\.\d+)", text)
    return m.group(1) if m else ""


def _chrome_major_version(version):
    m = re.match(r"(\d+)", version or "")
    return m.group(1) if m else "125"


def _build_user_agents(chrome_major):
    chrome_version = f"{chrome_major}.0.0.0"
    return [
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36",
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36 Edg/{chrome_version}",
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36",
        f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36",
    ]


BROWSER_VERSION = _env("BROWSER_VERSION", _detect_browser_version(BROWSER_PATH))
BROWSER_MAJOR_VERSION = _env("BROWSER_MAJOR_VERSION", _chrome_major_version(BROWSER_VERSION))

# ============================================================
# Account defaults (register.py)
# ============================================================
DEFAULT_PASSWORD = _env("DEFAULT_PASSWORD", "")

# ============================================================
# Fingerprint randomization (register.py / oauth_import.py)
# ============================================================
WINDOW_SIZES = [
    (1366, 768), (1440, 900), (1536, 864), (1600, 900),
    (1280, 800), (1920, 1080), (1680, 1050), (1360, 768),
]
USER_AGENTS = _build_user_agents(BROWSER_MAJOR_VERSION)
TIMEZONES = ["America/Santiago", "America/New_York", "America/Los_Angeles", "Europe/London"]
LANGUAGES = ["en-US,en;q=0.9", "en-US,en;q=0.9,es;q=0.8", "en-GB,en;q=0.9"]

# ============================================================
# Paths
# ============================================================
SCRIPT = os.path.expanduser(_env("SCRIPT", os.path.join(PROJECT_ROOT, "step_04_register", "register.py")))
LOG_DIR = os.path.expanduser(_env("LOG_DIR", "~/auto_batch_logs"))
STATE_FILE = os.path.expanduser(_env("STATE_FILE", "~/auto_batch_state.json"))
ACCOUNTS_LOG = _env("ACCOUNTS_LOG", "/home/ubuntu/chatgpt-accounts-new.jsonl")
