#!/usr/bin/env python3
"""
Shared configuration for auto_batch_monitor, register, and oauth_import.
Secrets can be provided through step_01_config/local_secrets.py or environment variables.
"""
import os

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
]

# Fallback countries for buying numbers (register.py)
# (hero_id, dial_code, iso, name) - preferred order
FALLBACK_COUNTRIES = [
    (151, "56", "CL", "Chile"),
    (16,  "44", "GB", "UK"),
    (4,   "63", "PH", "Philippines"),
    (73,  "73", "IN", "India"),
]

# ============================================================
# Mihomo Proxy (auto_batch_monitor)
# ============================================================
MIHOMO_API = _env("MIHOMO_API", "http://127.0.0.1:9091")
PROXY_PORT = _env_int("PROXY_PORT", 7892)

PROXIES = [
    {"name": "direct", "mihomo": None},           # No proxy (OC24 direct)
    {"name": "jp-residential", "mihomo": "jp-residential"},
    {"name": "us99-ss", "mihomo": "us99-ss"},
    {"name": "kkyun-ss", "mihomo": "kkyun-ss"},
]

MAX_PER_PROXY = _env_int("MAX_PER_PROXY", 10)
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
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]
TIMEZONES = ["America/Santiago", "America/New_York", "America/Los_Angeles", "Europe/London"]
LANGUAGES = ["en-US,en;q=0.9", "en-US,en;q=0.9,es;q=0.8", "en-GB,en;q=0.9"]

# ============================================================
# Paths
# ============================================================
SCRIPT = os.path.expanduser(_env("SCRIPT", os.path.join(PROJECT_ROOT, "step_04_register", "register.py")))
LOG_DIR = os.path.expanduser(_env("LOG_DIR", "~/auto_batch_logs"))
STATE_FILE = os.path.expanduser(_env("STATE_FILE", "~/auto_batch_state.json"))
ACCOUNTS_LOG = _env("ACCOUNTS_LOG", "/home/ubuntu/chatgpt-accounts-new.jsonl")
