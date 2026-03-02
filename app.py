#!/usr/bin/env python3
"""
SmartPI Dashboard — Flask Backend
Connects to Home Assistant via REST + WebSocket to relay real-time
SmartPI thermostat data to the browser dashboard.
"""

import os

from flask import Flask, render_template, jsonify, request, abort

from config import (
    CLIMATE_ENTITY, FLASK_PORT, HA_URL, WS_URL,
    state_store, ENTITY_ID_RE, log, check_ha_token,
)
from transforms import (
    SMARTPI_GROUPS, flatten_smartpi_attrs, extract_smartpi_data, snapshot_for_history,
)
from ha_client import ha_discover_smartpi_entities, ha_get_history
from ws_listener import start_ws_thread

# ─── Application ─────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(32).hex())


# ─── Security Headers ────────────────────────────────────────────

@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response


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
def api_entities():
    """Return the list of discovered SmartPI climate entities."""
    entities = ha_discover_smartpi_entities()
    return jsonify({
        "ok": True,
        "default": CLIMATE_ENTITY,
        "entities": entities,
    })


@app.route("/api/state")
def api_state():
    """Return the current SmartPI state grouped by category."""
    entity_id = _resolve_entity_id()
    if entity_id not in state_store["entities"]:
        abort(404, description="Unknown entity")
    estore = state_store["entities"][entity_id]
    attrs = estore["attributes"]
    climate = estore["climate"]

    return jsonify({
        "ok": True,
        "connected": state_store["connected"],
        "entity_id": entity_id,
        "last_update": estore["last_update"],
        "hvac_mode": climate.get("state", "unknown"),
        "hvac_action": attrs.get("hvac_action", "unknown"),
        "groups": extract_smartpi_data(attrs),
        "raw_attributes": attrs,
    })


@app.route("/api/history")
def api_history():
    """Return the rolling in-memory history."""
    entity_id = _resolve_entity_id()
    if entity_id not in state_store["entities"]:
        abort(404, description="Unknown entity")
    estore = state_store["entities"][entity_id]
    return jsonify({
        "ok": True,
        "count": len(estore["history"]),
        "data": estore["history"],
    })


@app.route("/api/ha-history")
def api_ha_history():
    """Fetch history from HA REST API (heavier, for initial load)."""
    entity_id = _resolve_entity_id()
    # Only allow querying known entities to prevent SSRF
    known = state_store.get("known_entities", [])
    if entity_id not in known and entity_id != CLIMATE_ENTITY:
        abort(404, description="Unknown entity")
    try:
        hours = int(request.args.get("hours", 24))
    except (ValueError, TypeError):
        hours = 24
    hours = max(1, min(hours, 168))  # Clamp between 1 and 7 days
    history = ha_get_history(entity_id, hours)

    # Transform HA history format to our format
    points = []
    for entry in history:
        raw_attrs = entry.get("attributes", {})
        attrs = flatten_smartpi_attrs(raw_attrs)
        points.append(snapshot_for_history(attrs))
        # Override timestamp with HA's last_changed
        points[-1]["ts"] = entry.get("last_changed")

    return jsonify({
        "ok": True,
        "count": len(points),
        "data": points,
    })


@app.route("/api/config")
def api_config():
    """Return the dashboard configuration (groups, keys)."""
    return jsonify({
        "ok": True,
        "entity_id": CLIMATE_ENTITY,
        "groups": {
            gid: {"label": g["label"], "icon": g["icon"], "keys": g["keys"]}
            for gid, g in SMARTPI_GROUPS.items()
        },
    })


@app.route("/api/block-diagram")
def api_block_diagram():
    """Return the SVG block diagram metadata (tooltip data)."""
    return jsonify({
        "ok": True,
        "blocks": {
            "sp_brut": {"label": "SP_brut", "group": "setpoint_filter"},
            "sp_filter": {"label": "Setpoint Filter", "group": "setpoint_filter"},
            "summer_p": {"label": "Σ Proportionnel", "group": "regulation"},
            "summer_i": {"label": "Σ Intégral", "group": "regulation"},
            "kp": {"label": "Kp", "group": "regulation", "attr": "smartpi_kp"},
            "ki": {"label": "Ki·∫", "group": "regulation", "attr": "smartpi_ki"},
            "summer_pi": {"label": "Σ PI+FF", "group": "regulation"},
            "governance": {"label": "Governance", "group": "governance", "attr": "smartpi_regime"},
            "rate_limit": {"label": "Rate Limiter", "group": "regulation"},
            "timing": {"label": "Timing", "group": "cycle"},
            "pwm": {"label": "PWM", "group": "cycle"},
            "process": {"label": "Bâtiment 1R1C", "group": "model"},
            "sensor": {"label": "T_in", "group": "regulation", "attr": "current_temperature"},
            "text": {"label": "T_ext", "group": "model"},
            "feedforward": {"label": "Feedforward", "group": "feedforward", "attr": "smartpi_ff_u_ff"},
            "antiwindup": {"label": "Anti-Windup", "group": "regulation"},
            "ab_estimator": {"label": "ABEstimator", "group": "model", "attr": "smartpi_a"},
            "deadtime": {"label": "DeadTime Est.", "group": "model", "attr": "smartpi_deadtime_heat_s"},
            "gain_scheduler": {"label": "GainScheduler", "group": "regulation"},
            "twin": {"label": "ThermalTwin", "group": "twin", "attr": "smartpi_twin_t_hat"},
            "autocalib": {"label": "AutoCalibTrigger", "group": "calibration"},
            "calibration": {"label": "Calibration FSM", "group": "calibration"},
            "deadband": {"label": "Deadband Mgr", "group": "regulation"},
            "guards": {"label": "Guards", "group": "governance"},
            "learn_win": {"label": "LearningWindow", "group": "model"},
            "phase": {"label": "Phase Machine", "group": "governance", "attr": "smartpi_phase"},
        },
    })


# ─── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
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
    app.run(
        host="0.0.0.0",
        port=FLASK_PORT,
        debug=False,  # Don't use debug mode with background threads
        threaded=True,
    )
