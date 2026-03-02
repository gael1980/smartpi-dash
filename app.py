#!/usr/bin/env python3
"""
SmartPI Dashboard — Flask Backend
Connects to Home Assistant via REST + WebSocket to relay real-time
SmartPI thermostat data to the browser dashboard.
"""

import os
import re
import json
import asyncio
import threading
import time
import logging
from datetime import datetime, timedelta, timezone

import requests
import websockets
from flask import Flask, render_template, jsonify, request, abort
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
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(32).hex())

# Strict regex for HA entity IDs (e.g. climate.thermostat_cuisine)
_ENTITY_ID_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")

# ─── Shared State (thread-safe via GIL for simple reads/writes) ──
state_store = {
    "entities": {},          # {entity_id: {climate, attributes, sensors, last_update, history}}
    "connected": False,      # WebSocket connected?
    "known_entities": [],    # [{entity_id, friendly_name}] — SmartPI climate entities
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
            "smartpi_u_pi", "smartpi_u_cmd", "smartpi_u_applied", "smartpi_u_limited",
            "smartpi_aw_du",
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
            "smartpi_ff_gate", "smartpi_ff_scale",
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


def _flatten_smartpi_attrs(raw_attrs: dict) -> dict:
    """Flatten the nested HA attributes so that SmartPI data is at the top level.

    HA stores SmartPI data under raw_attrs["specific_states"]["smart_pi"]
    with keys like 'Kp', 'governance_regime', 'pred.twin_T_hat', etc.
    We flatten them to 'smartpi_kp', 'smartpi_regime', 'smartpi_twin_t_hat', etc.
    """
    flat = dict(raw_attrs)  # start with top-level attrs (current_temperature, etc.)

    specific = raw_attrs.get("specific_states", {})
    if not isinstance(specific, dict):
        return flat

    # ext_current_temperature lives directly in specific_states
    ext_temp = specific.get("ext_current_temperature")
    if ext_temp is not None:
        flat["smartpi_t_ext"] = ext_temp

    spi = specific.get("smart_pi", {})
    if not isinstance(spi, dict):
        return flat

    # Explicit mapping from nested smart_pi keys → flat smartpi_ keys
    MAPPING = {
        # Regulation
        "Kp": "smartpi_kp",
        "Ki": "smartpi_ki",
        "error_p": "smartpi_error_p",
        "integral_error": "smartpi_error_i",
        "u_pi": "smartpi_u_pi",
        "u_cmd": "smartpi_u_cmd",
        "u_applied": "smartpi_u_applied",
        "u_limited": "smartpi_u_limited",
        "u_ff": "smartpi_u_ff",
        "u_p": "smartpi_u_p",
        "u_i": "smartpi_u_i",
        "aw_du": "smartpi_aw_du",
        "on_percent": "smartpi_on_percent",
        # We also keep the top-level target from filtered_setpoint
        "filtered_setpoint": "smartpi_sp_for_p",
        # Setpoint filter
        "near_band_deg": "smartpi_near_band_deg",
        "near_band_above_deg": "smartpi_near_band_above_deg",
        "near_band_below_deg": "smartpi_near_band_below_deg",
        "in_near_band": "smartpi_in_near_band",
        "in_deadband": "smartpi_in_deadband",
        # Thermal model
        "a": "smartpi_a",
        "b": "smartpi_b",
        "tau_min": "smartpi_tau_min",
        "tau_reliable": "smartpi_tau_reliable",
        "deadtime_heat_s": "smartpi_deadtime_heat_s",
        "deadtime_cool_s": "smartpi_deadtime_cool_s",
        "deadtime_heat_reliable": "smartpi_deadtime_heat_reliable",
        "deadtime_cool_reliable": "smartpi_deadtime_cool_reliable",
        "learn_ok_count_a": "smartpi_learn_ok_count_a",
        "learn_ok_count_b": "smartpi_learn_ok_count_b",
        # Governance
        "governance_regime": "smartpi_regime",
        "phase": "smartpi_phase",
        "i_mode": "smartpi_integral_state",
        "last_decision_gains": "smartpi_governance_action",
        "last_decision_thermal": "smartpi_governance_diag_code",
        "guard_cut_active": "smartpi_guard_cut_active",
        "hysteresis_thermal_guard": "smartpi_thermal_guard_active",
        # Feedforward
        "ff_raw": "smartpi_ff_u_ff",
        "ff_reason": "smartpi_ff_gate",
        "ff_warmup_cycles": "smartpi_ff_warmup",
        "ff_warmup_ok_count": "smartpi_ff_warmup_ok_count",
        "ff_warmup_scale": "smartpi_ff_scale",
        # Note: ff_enabled is derived from ff_reason != "ff_none"
        # Calibration
        "calibration_state": "smartpi_calibration_state",
        "autocalib_state": "smartpi_autocalib_state",
        "autocalib_model_degraded": "smartpi_autocalib_model_degraded",
        "autocalib_triggered_params": "smartpi_autocalib_triggered_params",
        "autocalib_retry_count": "smartpi_autocalib_retry_count",
        "autocalib_snapshot_age_h": "smartpi_autocalib_snapshot_age_h",
        # Setpoint filter
        "regulation_mode": "smartpi_filter_mode",
        # Cycle PWM
        "cycle_min": "smartpi_cycle_min",
        "sat": "smartpi_cycle_state",
        "forced_by_timing": "smartpi_rate_limit",
    }

    for src, dst in MAPPING.items():
        val = spi.get(src)
        if val is not None:
            flat[dst] = val

    # ff_enabled is derived
    flat["smartpi_ff_enabled"] = spi.get("ff_reason", "ff_none") != "ff_none"
    # ff_k_ff: b/a if both known
    a_val = spi.get("a")
    b_val = spi.get("b")
    if a_val and b_val and a_val != 0:
        flat["smartpi_ff_k_ff"] = b_val / a_val

    # sp_brut from top-level temperature
    if "temperature" in raw_attrs:
        flat["smartpi_sp_brut"] = raw_attrs["temperature"]

    # Pred / twin data is nested one more level
    pred = spi.get("pred", {})
    if isinstance(pred, dict):
        PRED_MAPPING = {
            "twin_T_hat": "smartpi_twin_t_hat",
            "twin_innovation": "smartpi_twin_innovation",
            "twin_d_hat": "smartpi_twin_d_hat_ema",
            "twin_rmse_30": "smartpi_twin_rmse",
            "twin_T_steady": "smartpi_twin_t_steady",
            "twin_cusum_pos": "smartpi_twin_cusum",
            "eta_reason": "smartpi_twin_eta_reason",
        }
        for src, dst in PRED_MAPPING.items():
            val = pred.get(src)
            if val is not None:
                flat[dst] = val

        # ETA: use whichever is available
        eta = pred.get("eta_heat_100_s") or pred.get("eta_cool_0_s")
        if eta is not None:
            flat["smartpi_twin_eta_s"] = eta

    # Also bring target_temperature to top level if missing
    if flat.get("target_temperature") is None:
        cs = specific.get("current_state", {})
        if isinstance(cs, dict) and cs.get("target_temperature") is not None:
            flat["target_temperature"] = cs["target_temperature"]

    # min_on / min_off from configuration
    config = raw_attrs.get("configuration", {})
    if isinstance(config, dict):
        if config.get("minimal_activation_delay_sec") is not None:
            flat["smartpi_min_on_s"] = config["minimal_activation_delay_sec"]
        if config.get("minimal_deactivation_delay_sec") is not None:
            flat["smartpi_min_off_s"] = config["minimal_deactivation_delay_sec"]

    return flat


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
        "u_pi": attrs.get("smartpi_u_pi"),
        "u_cmd": attrs.get("smartpi_u_cmd"),
        "u_limited": attrs.get("smartpi_u_limited"),
        "u_p": attrs.get("smartpi_u_p"),
        "u_i": attrs.get("smartpi_u_i"),
        "twin_t_hat": attrs.get("smartpi_twin_t_hat"),
        "twin_innovation": attrs.get("smartpi_twin_innovation"),
        "twin_d_hat": attrs.get("smartpi_twin_d_hat_ema"),
        "error_p": attrs.get("smartpi_error_p"),
        "kp": attrs.get("smartpi_kp"),
        "ki": attrs.get("smartpi_ki"),
        "regime": attrs.get("smartpi_regime"),
        "phase": attrs.get("smartpi_phase"),
        "near_band_above": attrs.get("smartpi_near_band_above_deg"),
        "near_band_below": attrs.get("smartpi_near_band_below_deg"),
        "in_deadband": attrs.get("smartpi_in_deadband"),
        "ff_gate": attrs.get("smartpi_ff_gate"),
        "ff_scale": attrs.get("smartpi_ff_scale"),
        "ff_k_ff": attrs.get("smartpi_ff_k_ff"),
    }


def _get_entity_store(entity_id: str) -> dict:
    """Get or initialize the state store for a given entity."""
    if entity_id not in state_store["entities"]:
        state_store["entities"][entity_id] = {
            "climate": {},
            "attributes": {},
            "sensors": {},
            "last_update": None,
            "history": [],
        }
    return state_store["entities"][entity_id]


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


_entities_cache = {"data": [], "ts": 0}
ENTITIES_CACHE_TTL = 60  # seconds


def ha_discover_smartpi_entities() -> list[dict]:
    """Discover all climate entities with SmartPI attributes from HA."""
    now = time.time()
    if _entities_cache["data"] and now - _entities_cache["ts"] < ENTITIES_CACHE_TTL:
        return _entities_cache["data"]

    try:
        r = requests.get(
            f"{HA_URL}/api/states",
            headers=ha_headers(),
            timeout=15,
        )
        r.raise_for_status()
        all_states = r.json()
    except Exception as e:
        log.error("Failed to discover entities: %s", e)
        return _entities_cache["data"]  # return stale cache on error

    entities = []
    for state in all_states:
        eid = state.get("entity_id", "")
        if not eid.startswith("climate."):
            continue
        attrs = state.get("attributes", {})
        specific = attrs.get("specific_states", {})
        if isinstance(specific, dict) and "smart_pi" in specific:
            entities.append({
                "entity_id": eid,
                "friendly_name": attrs.get("friendly_name", eid),
            })

    # Sort: default entity first, then alphabetical
    entities.sort(key=lambda e: (e["entity_id"] != CLIMATE_ENTITY, e["friendly_name"]))

    _entities_cache["data"] = entities
    _entities_cache["ts"] = now
    state_store["known_entities"] = [e["entity_id"] for e in entities]
    log.info("Discovered %d SmartPI entities: %s", len(entities),
             [e["entity_id"] for e in entities])
    return entities


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

                # Discover SmartPI entities and do initial REST fetch
                discovered = ha_discover_smartpi_entities()
                known_ids = set(e["entity_id"] for e in discovered)

                # Ensure the default entity is always tracked even if discovery fails
                if CLIMATE_ENTITY not in known_ids:
                    known_ids.add(CLIMATE_ENTITY)

                for eid in known_ids:
                    initial = ha_get_state(eid)
                    if initial:
                        estore = _get_entity_store(eid)
                        raw_attrs = initial.get("attributes", {})
                        attrs = _flatten_smartpi_attrs(raw_attrs)
                        estore["climate"] = initial
                        estore["attributes"] = attrs
                        estore["last_update"] = initial.get("last_changed")
                        log.info("Initial state loaded for %s", eid)

                # Phase 4: Listen for events
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") != "event":
                        continue

                    event = msg.get("event", {})
                    data = event.get("data", {})
                    entity_id = data.get("entity_id", "")

                    # Track all known SmartPI climate entities
                    if entity_id in known_ids:
                        new_state = data.get("new_state", {})
                        raw_attrs = new_state.get("attributes", {})
                        attrs = _flatten_smartpi_attrs(raw_attrs)
                        estore = _get_entity_store(entity_id)
                        estore["climate"] = new_state
                        estore["attributes"] = attrs
                        estore["last_update"] = new_state.get("last_changed")

                        # Append to rolling history
                        snap = _snapshot_for_history(attrs)
                        estore["history"].append(snap)
                        if len(estore["history"]) > MAX_HISTORY:
                            estore["history"] = estore["history"][-MAX_HISTORY:]

                        log.debug("[%s] State updated: T=%.1f, on_pct=%s",
                                  entity_id,
                                  attrs.get("current_temperature", 0),
                                  attrs.get("on_percent", "?"))

                    # Also capture related sensor entities for any known climate entity
                    elif any(entity_id.startswith(eid.replace("climate.", "sensor."))
                             for eid in known_ids):
                        # Find which climate entity this sensor belongs to
                        for eid in known_ids:
                            prefix = eid.replace("climate.", "sensor.")
                            if entity_id.startswith(prefix):
                                new_state = data.get("new_state", {})
                                estore = _get_entity_store(eid)
                                estore["sensors"][entity_id] = {
                                    "state": new_state.get("state"),
                                    "attributes": new_state.get("attributes", {}),
                                    "last_changed": new_state.get("last_changed"),
                                }
                                break

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
    if not _ENTITY_ID_RE.match(eid):
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
        "groups": _extract_smartpi_data(attrs),
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
        attrs = _flatten_smartpi_attrs(raw_attrs)
        points.append(_snapshot_for_history(attrs))
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
    log.info("  HA URL:         %s", HA_URL)
    log.info("  Default Entity: %s", CLIMATE_ENTITY)
    log.info("  WS URL:         %s", WS_URL)
    log.info("  Port:           %s", FLASK_PORT)
    log.info("  Multi-entity:   auto-discovery enabled")
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
