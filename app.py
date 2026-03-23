#!/usr/bin/env python3
"""
SmartPI Dashboard — Flask Backend
Connects to Home Assistant via REST + WebSocket to relay real-time
SmartPI thermostat data to the browser dashboard.
"""

import os
import time

from flask import Flask, render_template, jsonify, request, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import (
    CLIMATE_ENTITY, FLASK_PORT, HA_URL, WS_URL,
    state_store, ENTITY_ID_RE, log, check_ha_token,
)
from transforms import (
    SMARTPI_GROUPS, flatten_smartpi_attrs, extract_smartpi_data, snapshot_for_history,
    ensure_utc_iso,
)
from ha_client import ha_discover_smartpi_entities, ha_get_history
from ws_listener import start_ws_thread

# ─── Server-side caches ──────────────────────────────────────────

# Keyed by (entity_id, hours) → (timestamp, points)
_ha_history_cache: dict = {}
HA_HISTORY_CACHE_TTL = 60  # seconds
_HA_HISTORY_CACHE_MAX = 50  # max entries to prevent unbounded growth

# Static responses computed once on first request
_config_data: dict | None = None
_block_diagram_data: dict | None = None


# ─── Application ─────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(32).hex())

# ─── Rate Limiting ───────────────────────────────────────────────
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per hour"],
    storage_uri="memory://",
)


# ─── Security Headers ────────────────────────────────────────────

@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    if request.path.startswith("/api/") and "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "no-store, private"
    return response


# ─── Request Logging ─────────────────────────────────────────────

@app.before_request
def log_request():
    if request.path.startswith("/api/"):
        log.info("%s %s from %s", request.method, request.path, request.remote_addr)


# ─── Flask Routes ────────────────────────────────────────────────

def _resolve_entity_id() -> str:
    """Get entity_id from query param, falling back to CLIMATE_ENTITY.
    Validates the format to prevent SSRF / path traversal."""
    eid = request.args.get("entity_id", CLIMATE_ENTITY)
    if not ENTITY_ID_RE.match(eid):
        abort(400, description="Invalid entity_id format")
    return eid


@app.route("/")
def index():
    """Serve the main dashboard."""
    return render_template(
        "dashboard.html",
        climate_entity=CLIMATE_ENTITY,
    )


@app.route("/api/entities")
@limiter.limit("10/minute")
def api_entities():
    """Return the list of discovered SmartPI climate entities."""
    entities = ha_discover_smartpi_entities()
    return jsonify({
        "ok": True,
        "default": CLIMATE_ENTITY,
        "entities": entities,
    })


@app.route("/api/state")
@limiter.limit("60/minute")
def api_state():
    """Return the current SmartPI state grouped by category."""
    entity_id = _resolve_entity_id()
    if entity_id not in state_store["entities"]:
        abort(404, description="Unknown entity")
    estore = state_store["entities"][entity_id]
    attrs = estore["attributes"]
    climate = estore["climate"]

    # ETag based on last_update — skip full response if state unchanged
    last_update = estore["last_update"] or ""
    etag = f'"{last_update}"'
    if last_update and request.headers.get("If-None-Match") == etag:
        return "", 304

    resp = jsonify({
        "ok": True,
        "connected": state_store["connected"],
        "entity_id": entity_id,
        "last_update": last_update,
        "hvac_mode": climate.get("state", "unknown"),
        "hvac_action": attrs.get("hvac_action", "unknown"),
        "groups": extract_smartpi_data(attrs),
        "raw_attributes": attrs,
    })
    resp.headers["ETag"] = etag
    return resp


@app.route("/api/history")
@limiter.limit("60/minute")
def api_history():
    """Return the rolling in-memory history."""
    entity_id = _resolve_entity_id()
    if entity_id not in state_store["entities"]:
        abort(404, description="Unknown entity")
    estore = state_store["entities"][entity_id]
    return jsonify({
        "ok": True,
        "count": len(estore["history"]),
        "data": list(estore["history"]),
    })


@app.route("/api/ha-history")
@limiter.limit("10/minute")
def api_ha_history():
    """Fetch history from HA REST API (heavier, for initial load)."""
    entity_id = _resolve_entity_id()
    # Only allow querying known entities to prevent SSRF
    known = state_store.get("known_entities", [])
    if entity_id not in known and entity_id not in state_store["entities"]:
        abort(404, description="Unknown entity")
    hours_raw = request.args.get("hours", "24")
    try:
        hours = int(hours_raw)
    except (ValueError, TypeError):
        log.warning("Invalid 'hours' param: %r from %s", hours_raw[:20], request.remote_addr)
        hours = 24
    hours = max(1, min(hours, 168))  # Clamp between 1 and 7 days

    # Serve from cache if still fresh (avoids hammering HA REST every 15s)
    cache_key = (entity_id, hours)
    cached = _ha_history_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < HA_HISTORY_CACHE_TTL:
        points = cached[1]
    else:
        history = ha_get_history(entity_id, hours)
        points = []
        for entry in history:
            raw_attrs = entry.get("attributes", {})
            attrs = flatten_smartpi_attrs(raw_attrs)
            points.append(snapshot_for_history(attrs))
            points[-1]["ts"] = ensure_utc_iso(entry.get("last_changed"))
        # Evict expired entries if cache is full
        if len(_ha_history_cache) >= _HA_HISTORY_CACHE_MAX:
            now = time.monotonic()
            expired = [k for k, v in _ha_history_cache.items() if now - v[0] >= HA_HISTORY_CACHE_TTL]
            for k in expired:
                del _ha_history_cache[k]
            # If still full, drop the oldest entry
            if len(_ha_history_cache) >= _HA_HISTORY_CACHE_MAX:
                oldest = min(_ha_history_cache, key=lambda k: _ha_history_cache[k][0])
                del _ha_history_cache[oldest]
        _ha_history_cache[cache_key] = (time.monotonic(), points)

    return jsonify({
        "ok": True,
        "count": len(points),
        "data": points,
    })


@app.route("/api/config")
@limiter.exempt
def api_config():
    """Return the dashboard configuration (groups, keys)."""
    global _config_data
    if _config_data is None:
        _config_data = {
            "ok": True,
            "entity_id": CLIMATE_ENTITY,
            "groups": {
                gid: {"label": g["label"], "icon": g["icon"], "keys": g["keys"]}
                for gid, g in SMARTPI_GROUPS.items()
            },
        }
    resp = jsonify(_config_data)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/api/block-diagram")
@limiter.exempt
def api_block_diagram():
    """Return the SVG block diagram metadata (tooltip data)."""
    global _block_diagram_data
    if _block_diagram_data is None:
        _block_diagram_data = {
        "ok": True,
        "blocks": {
            "sp_brut": {"label": "SP_brut", "group": "setpoint_filter"},
            "sp_filter": {"label": "Setpoint Filter Dual-Track", "group": "setpoint_filter", "attr": "smartpi_sp_for_p"},
            "summer_p": {"label": "Σ Proportionnel", "group": "regulation"},
            "summer_i": {"label": "Σ Intégral", "group": "regulation"},
            "kp": {"label": "Kp", "group": "regulation", "attr": "smartpi_kp"},
            "ki": {"label": "Ki·∫", "group": "regulation", "attr": "smartpi_ki"},
            "summer_pi": {"label": "Σ PI + FF2/FF3", "group": "regulation", "attr": "smartpi_u_cmd"},
            "governance": {"label": "Gouvernance", "group": "governance", "attr": "smartpi_regime"},
            "rate_limit": {"label": "Rate Limiter", "group": "regulation"},
            "timing": {"label": "Timing", "group": "cycle", "attr": "smartpi_committed_on_percent"},
            "pwm": {"label": "PWM", "group": "cycle", "attr": "on_percent"},
            "process": {"label": "Bâtiment 1R1C", "group": "model"},
            "sensor": {"label": "T_in", "group": "regulation", "attr": "current_temperature"},
            "text": {"label": "T_ext", "group": "model"},
            "feedforward": {"label": "Feedforward FF2 + FF3", "group": "feedforward", "attr": "smartpi_ff_u_ff"},
            "antiwindup": {"label": "Anti-Windup", "group": "regulation"},
            "ab_estimator": {"label": "ABEstimator", "group": "model", "attr": "smartpi_a"},
            "deadtime": {"label": "DeadTime Est.", "group": "model", "attr": "smartpi_deadtime_heat_s"},
            "gain_scheduler": {"label": "GainScheduler", "group": "regulation"},
            "twin": {"label": "ThermalTwin", "group": "twin", "attr": "smartpi_twin_status"},
            "autocalib": {"label": "AutoCalibTrigger", "group": "calibration"},
            "calibration": {"label": "Calibration FSM", "group": "calibration"},
            "deadband": {"label": "Deadband Mgr", "group": "regulation", "attr": "smartpi_deadband_power_source"},
            "guards": {"label": "Protections", "group": "governance"},
            "learn_win": {"label": "LearningWindow", "group": "model", "attr": "smartpi_learn_progress_percent"},
            "phase": {"label": "Phase Machine", "group": "governance", "attr": "smartpi_phase"},
        },
        }
    resp = jsonify(_block_diagram_data)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/health")
@limiter.exempt
def health():
    """Health check endpoint for monitoring / load balancers."""
    return jsonify({"ok": True, "connected": state_store["connected"]})


# ─── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Prevent accidental debug mode activation (Werkzeug debugger = RCE risk)
    if os.getenv("FLASK_DEBUG", "").lower() in ("1", "true"):
        log.critical("FLASK_DEBUG is forbidden (Werkzeug interactive debugger = RCE risk). Exiting.")
        raise SystemExit(1)

    check_ha_token()

    log.info("=" * 60)
    log.info("SmartPI Dashboard")
    log.info("  HA URL:         %s", HA_URL)
    log.info("  Default Entity: %s", CLIMATE_ENTITY)
    log.info("  WS URL:         %s", WS_URL)
    log.info("  Port:           %s", FLASK_PORT)
    log.info("  Multi-entity:   auto-discovery enabled")
    log.info("=" * 60)

    # Start WebSocket listener
    start_ws_thread()

    # Start Flask
    FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
    if FLASK_HOST not in ("127.0.0.1", "localhost", "::1"):
        log.warning(
            "SECURITY: FLASK_HOST=%s exposes the dashboard beyond localhost. "
            "There is no authentication — restrict network access externally.",
            FLASK_HOST,
        )
    app.run(
        host=FLASK_HOST,
        port=FLASK_PORT,
        debug=False,  # Don't use debug mode with background threads
        threaded=True,
    )
