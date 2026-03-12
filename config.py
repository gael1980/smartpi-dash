"""Configuration, logging, shared state, and validation."""

import os
import re
import stat
import logging
from collections import deque

from dotenv import load_dotenv

# ─── Environment ─────────────────────────────────────────────────
load_dotenv()

HA_URL = os.getenv("HA_URL", "http://localhost:8123").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")
CLIMATE_ENTITY = os.getenv("CLIMATE_ENTITY", "climate.thermostat")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))

# Derive the WebSocket URL from the HTTP URL
WS_URL = HA_URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"

# ─── Logging ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("smartpi-dash")

# ─── Security warnings ──────────────────────────────────────────
if HA_URL.startswith("http://") and "localhost" not in HA_URL and "127.0.0.1" not in HA_URL:
    log.warning("SECURITY: HA_URL uses plain HTTP. HA_TOKEN is transmitted in clear text. Use HTTPS.")

_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    _env_mode = os.stat(_env_path).st_mode
    if _env_mode & (stat.S_IRGRP | stat.S_IROTH):
        log.warning("SECURITY: .env is readable by group/other. Fix with: chmod 600 .env")

# ─── Validation ──────────────────────────────────────────────────
# Strict regex for HA entity IDs (e.g. climate.thermostat_cuisine)
ENTITY_ID_RE = re.compile(r"^[a-z_]+\.[a-z0-9_-]+$")

# ─── Shared State (thread-safe via GIL for simple reads/writes) ──
state_store = {
    "entities": {},          # {entity_id: {climate, attributes, sensors, last_update, history}}
    "connected": False,      # WebSocket connected?
    "known_entities": [],    # [entity_id, ...] — discovered SmartPI climate entities
}

MAX_HISTORY = 500


def get_entity_store(entity_id: str) -> dict:
    """Get or initialize the state store for a given entity."""
    if entity_id not in state_store["entities"]:
        state_store["entities"][entity_id] = {
            "climate": {},
            "attributes": {},
            "sensors": {},
            "last_update": None,
            "history": deque(maxlen=MAX_HISTORY),
        }
    return state_store["entities"][entity_id]


def check_ha_token():
    """Fail fast if HA_TOKEN is not configured or obviously invalid."""
    if not HA_TOKEN:
        log.critical("HA_TOKEN is empty or not set. Set it in .env or as an environment variable.")
        raise SystemExit(1)
    # HA long-lived access tokens are JWTs: three base64url segments separated by dots
    parts = HA_TOKEN.split(".")
    if len(parts) != 3 or not all(len(p) > 0 for p in parts):
        log.critical("HA_TOKEN does not look like a valid JWT (expected 3 dot-separated segments). Check .env configuration.")
        raise SystemExit(1)
