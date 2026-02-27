#!/usr/bin/env python3
"""
SmartPI Dashboard — Flask Backend
Connects to Home Assistant via REST + WebSocket to relay real-time
SmartPI thermostat data to the browser dashboard.
"""

import os
import json
import asyncio
import threading
import time
import logging
from datetime import datetime, timedelta, timezone

import requests
import websockets
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv

# ─── Configuration ───────────────────────────────────────────────
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

# ─── Application ─────────────────────────────────────────────────
app = Flask(__name__)

# ─── Shared State (thread-safe via GIL for simple reads/writes) ──
state_store = {
    "climate": {},           # Full climate entity state
    "attributes": {},        # Climate attributes (SmartPI data)
    "sensors": {},           # Related sensor entities
    "last_update": None,     # ISO timestamp of last state change
    "connected": False,      # WebSocket connected?
    "history": [],           # Rolling history (last 500 data points)
}

MAX_HISTORY = 500

# ─── Mapping: SmartPI attributes → dashboard groups ──────────────
SMARTPI_GROUPS = {
    "regulation": {
        "label": "Régulation PI",
        "icon": "⚡",
        "keys": [
            "current_temperature", "target_temperature", "on_percent",
            "smartpi_error_p", "smartpi_error_i",
            "smartpi_kp", "smartpi_ki", "smartpi_u_p", "smartpi_u_i", "smartpi_u_ff",
            "smartpi_u_pi", "smartpi_u_cmd", "smartpi_u_applied",
        ],
    },
    "model": {
        "label": "Modèle Thermique",
        "icon": "🏠",
        "keys": [
            "smartpi_a", "smartpi_b", "smartpi_tau_min",
            "smartpi_deadtime_heat_s", "smartpi_deadtime_cool_s",
            "smartpi_deadtime_heat_reliable", "smartpi_deadtime_cool_reliable",
            "smartpi_tau_reliable",
            "smartpi_learn_ok_count_a", "smartpi_learn_ok_count_b",
        ],
    },
    "twin": {
        "label": "Thermal Twin",
        "icon": "🔬",
        "keys": [
            "smartpi_twin_t_hat", "smartpi_twin_innovation",
            "smartpi_twin_d_hat_ema", "smartpi_twin_rmse",
            "smartpi_twin_cusum", "smartpi_twin_t_steady",
            "smartpi_twin_eta_s", "smartpi_twin_eta_reason",
        ],
    },
    "governance": {
        "label": "Gouvernance & Sécurité",
        "icon": "🛡️",
        "keys": [
            "smartpi_regime", "smartpi_phase",
            "smartpi_governance_action", "smartpi_governance_diag_code",
            "smartpi_integral_state",
            "smartpi_thermal_guard_active", "smartpi_guard_cut_active",
        ],
    },
    "feedforward": {
        "label": "Feedforward",
        "icon": "🎯",
        "keys": [
            "smartpi_ff_enabled", "smartpi_ff_k_ff",
            "smartpi_ff_u_ff", "smartpi_ff_warmup",
            "smartpi_ff_gate",
        ],
    },
    "calibration": {
        "label": "Calibration & AutoCalib",
        "icon": "🔧",
        "keys": [
            "smartpi_calibration_state",
            "smartpi_autocalib_state", "smartpi_autocalib_model_degraded",
            "smartpi_autocalib_triggered_params",
            "smartpi_autocalib_retry_count",
            "smartpi_autocalib_snapshot_age_h",
        ],
    },
    "setpoint_filter": {
        "label": "Filtre de Consigne",
        "icon": "📐",
        "keys": [
            "smartpi_sp_brut", "smartpi_sp_for_p",
            "smartpi_filter_mode", "smartpi_filter_tau_f",
        ],
    },
    "cycle": {
        "label": "Cycle PWM",
        "icon": "⏱️",
        "keys": [
            "smartpi_cycle_min", "smartpi_cycle_state",
            "smartpi_min_on_s", "smartpi_min_off_s",
            "smartpi_rate_limit",
        ],
    },
}

# Flattened list of all known SmartPI attribute keys
ALL_SMARTPI_KEYS = set()
for grp in SMARTPI_GROUPS.values():
    ALL_SMARTPI_KEYS.update(grp["keys"])


def _extract_smartpi_data(attrs: dict) -> dict:
    """Extract and group SmartPI-relevant attributes."""
    grouped = {}
    for gid, gdef in SMARTPI_GROUPS.items():
        grouped[gid] = {
            "label": gdef["label"],
            "icon": gdef["icon"],
            "values": {},
        }
        for key in gdef["keys"]:
            val = attrs.get(key)
            if val is None:
                # Try without smartpi_ prefix for standard HA attributes
                short = key.replace("smartpi_", "")
                val = attrs.get(short)
            grouped[gid]["values"][key] = val

    # Also collect any extra smartpi_ attributes not in our mapping
    extras = {}
    for k, v in attrs.items():
        if k.startswith("smartpi_") and k not in ALL_SMARTPI_KEYS:
            extras[k] = v
    if extras:
        grouped["extras"] = {
            "label": "Autres attributs SmartPI",
            "icon": "📋",
            "values": extras,
        }

    return grouped


def _snapshot_for_history(attrs: dict) -> dict:
    """Create a compact snapshot for the rolling history."""
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "t_in": attrs.get("current_temperature"),
        "t_target": attrs.get("temperature") or attrs.get("target_temperature"),
        "t_ext": attrs.get("smartpi_t_ext") or attrs.get("current_external_temperature"),
        "on_percent": attrs.get("on_percent"),
        "u_applied": attrs.get("smartpi_u_applied"),
        "u_ff": attrs.get("smartpi_ff_u_ff") or attrs.get("smartpi_u_ff"),
        "twin_t_hat": attrs.get("smartpi_twin_t_hat"),
        "twin_innovation": attrs.get("smartpi_twin_innovation"),
        "twin_d_hat": attrs.get("smartpi_twin_d_hat_ema"),
        "error_p": attrs.get("smartpi_error_p"),
        "kp": attrs.get("smartpi_kp"),
        "ki": attrs.get("smartpi_ki"),
        "regime": attrs.get("smartpi_regime"),
        "phase": attrs.get("smartpi_phase"),
    }


# ─── HA REST API helpers ─────────────────────────────────────────

def ha_headers() -> dict:
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }


def ha_get_state(entity_id: str) -> dict | None:
    """Fetch a single entity state via REST."""
    try:
        r = requests.get(
            f"{HA_URL}/api/states/{entity_id}",
            headers=ha_headers(),
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("REST fetch failed for %s: %s", entity_id, e)
        return None


def ha_get_history(entity_id: str, hours: int = 24) -> list:
    """Fetch history for an entity via REST."""
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        r = requests.get(
            f"{HA_URL}/api/history/period/{start.isoformat()}",
            headers=ha_headers(),
            params={
                "filter_entity_id": entity_id,
                "minimal_response": "true",
                "no_attributes": "false",
                "end_time": end.isoformat(),
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        return data[0] if data else []
    except Exception as e:
        log.error("History fetch failed: %s", e)
        return []


# ─── WebSocket listener (runs in background thread) ─────────────

async def _ws_listener():
    """Connect to HA WebSocket and subscribe to state changes."""
    msg_id = 1

    while True:
        try:
            log.info("Connecting to HA WebSocket: %s", WS_URL)
            async with websockets.connect(
                WS_URL,
                additional_headers={"Authorization": f"Bearer {HA_TOKEN}"},
                ping_interval=30,
                ping_timeout=10,
            ) as ws:
                # Phase 1: auth_required
                msg = json.loads(await ws.recv())
                if msg.get("type") != "auth_required":
                    log.warning("Unexpected first message: %s", msg.get("type"))

                # Phase 2: authenticate
                await ws.send(json.dumps({
                    "type": "auth",
                    "access_token": HA_TOKEN,
                }))
                msg = json.loads(await ws.recv())
                if msg.get("type") != "auth_ok":
                    log.error("Auth failed: %s", msg)
                    await asyncio.sleep(10)
                    continue

                log.info("WebSocket authenticated ✓")
                state_store["connected"] = True

                # Phase 3: Subscribe to state_changed events
                subscribe_id = msg_id
                msg_id += 1
                await ws.send(json.dumps({
                    "id": subscribe_id,
                    "type": "subscribe_events",
                    "event_type": "state_changed",
                }))

                # Also do an initial fetch via REST
                initial = ha_get_state(CLIMATE_ENTITY)
                if initial:
                    attrs = initial.get("attributes", {})
                    state_store["climate"] = initial
                    state_store["attributes"] = attrs
                    state_store["last_update"] = initial.get("last_changed")
                    log.info("Initial state loaded for %s", CLIMATE_ENTITY)

                # Phase 4: Listen for events
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") != "event":
                        continue

                    event = msg.get("event", {})
                    data = event.get("data", {})
                    entity_id = data.get("entity_id", "")

                    # We care about our climate entity and related sensors
                    if entity_id == CLIMATE_ENTITY:
                        new_state = data.get("new_state", {})
                        attrs = new_state.get("attributes", {})
                        state_store["climate"] = new_state
                        state_store["attributes"] = attrs
                        state_store["last_update"] = new_state.get("last_changed")

                        # Append to rolling history
                        snap = _snapshot_for_history(attrs)
                        state_store["history"].append(snap)
                        if len(state_store["history"]) > MAX_HISTORY:
                            state_store["history"] = state_store["history"][-MAX_HISTORY:]

                        log.debug("State updated: T=%.1f, on_pct=%s",
                                  attrs.get("current_temperature", 0),
                                  attrs.get("on_percent", "?"))

                    # Also capture related sensor entities
                    elif entity_id.startswith(CLIMATE_ENTITY.replace("climate.", "sensor.")):
                        new_state = data.get("new_state", {})
                        state_store["sensors"][entity_id] = {
                            "state": new_state.get("state"),
                            "attributes": new_state.get("attributes", {}),
                            "last_changed": new_state.get("last_changed"),
                        }

        except websockets.exceptions.ConnectionClosed:
            log.warning("WebSocket connection closed, reconnecting in 5s...")
            state_store["connected"] = False
            await asyncio.sleep(5)
        except Exception as e:
            log.error("WebSocket error: %s, reconnecting in 10s...", e)
            state_store["connected"] = False
            await asyncio.sleep(10)


def _start_ws_thread():
    """Start the WebSocket listener in a daemon thread."""
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_ws_listener())

    t = threading.Thread(target=run, daemon=True, name="ws-listener")
    t.start()
    log.info("WebSocket listener thread started")


# ─── Flask Routes ────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main dashboard."""
    return render_template(
        "dashboard.html",
        climate_entity=CLIMATE_ENTITY,
        ha_url=HA_URL,
    )


@app.route("/api/state")
def api_state():
    """Return the current SmartPI state grouped by category."""
    attrs = state_store["attributes"]
    climate = state_store["climate"]

    return jsonify({
        "ok": True,
        "connected": state_store["connected"],
        "entity_id": CLIMATE_ENTITY,
        "last_update": state_store["last_update"],
        "hvac_mode": climate.get("state", "unknown"),
        "hvac_action": attrs.get("hvac_action", "unknown"),
        "groups": _extract_smartpi_data(attrs),
        "raw_attributes": attrs,
    })


@app.route("/api/history")
def api_history():
    """Return the rolling in-memory history."""
    return jsonify({
        "ok": True,
        "count": len(state_store["history"]),
        "data": state_store["history"],
    })


@app.route("/api/ha-history")
def api_ha_history():
    """Fetch history from HA REST API (heavier, for initial load)."""
    hours = int(request.args.get("hours", 24))
    hours = min(hours, 168)  # Cap at 7 days
    history = ha_get_history(CLIMATE_ENTITY, hours)

    # Transform HA history format to our format
    points = []
    for entry in history:
        attrs = entry.get("attributes", {})
        points.append({
            "ts": entry.get("last_changed"),
            "t_in": attrs.get("current_temperature"),
            "t_target": attrs.get("temperature") or attrs.get("target_temperature"),
            "t_ext": attrs.get("smartpi_t_ext") or attrs.get("current_external_temperature"),
            "on_percent": attrs.get("on_percent"),
            "u_applied": attrs.get("smartpi_u_applied"),
            "u_ff": attrs.get("smartpi_ff_u_ff") or attrs.get("smartpi_u_ff"),
            "twin_t_hat": attrs.get("smartpi_twin_t_hat"),
            "twin_innovation": attrs.get("smartpi_twin_innovation"),
            "twin_d_hat": attrs.get("smartpi_twin_d_hat_ema"),
            "regime": attrs.get("smartpi_regime"),
            "phase": attrs.get("smartpi_phase"),
        })

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
        "ha_url": HA_URL,
        "groups": {
            gid: {"label": g["label"], "icon": g["icon"], "keys": g["keys"]}
            for gid, g in SMARTPI_GROUPS.items()
        },
    })


@app.route("/api/block-diagram")
def api_block_diagram():
    """Return the SVG block diagram metadata (tooltip data)."""
    # We embed the tooltip data from the original HTML
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
    log.info("=" * 60)
    log.info("SmartPI Dashboard")
    log.info("  HA URL:    %s", HA_URL)
    log.info("  Entity:    %s", CLIMATE_ENTITY)
    log.info("  WS URL:    %s", WS_URL)
    log.info("  Port:      %s", FLASK_PORT)
    log.info("=" * 60)

    # Start WebSocket listener
    _start_ws_thread()

    # Start Flask
    app.run(
        host="0.0.0.0",
        port=FLASK_PORT,
        debug=False,  # Don't use debug mode with background threads
        threaded=True,
    )
