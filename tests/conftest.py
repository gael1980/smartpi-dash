"""Shared fixtures for smartpi-dash tests."""

import os
import sys
import pytest
from collections import deque
from unittest.mock import patch

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set env vars before importing config / app
os.environ.setdefault("HA_URL", "http://localhost:8123")
os.environ.setdefault("HA_TOKEN", "test_token_that_is_long_enough_for_validation")
os.environ.setdefault("CLIMATE_ENTITY", "climate.test_thermostat")


@pytest.fixture()
def flask_app():
    """Return a Flask test app with WS listener disabled."""
    with patch("ws_listener.start_ws_thread"):
        from app import app as flask_application
        flask_application.config["TESTING"] = True
        flask_application.config["RATELIMIT_ENABLED"] = False
        yield flask_application


@pytest.fixture()
def client(flask_app):
    """Return a test client."""
    return flask_app.test_client()


@pytest.fixture()
def entity_id():
    return "climate.test_thermostat"


@pytest.fixture()
def populated_store(entity_id):
    """Populate state_store with a minimal entity entry, then clean up."""
    import config
    store = config.get_entity_store(entity_id)
    store["climate"] = {"state": "heat"}
    store["attributes"] = {
        "current_temperature": 19.5,
        "target_temperature": 21.0,
        "hvac_action": "heating",
        "smartpi_kp": 0.5,
        "smartpi_ki": 0.1,
    }
    store["last_update"] = "2024-01-01T12:00:00+00:00"
    store["history"].append({"ts": "2024-01-01T12:00:00+00:00", "t_in": 19.5})
    config.state_store["known_entities"] = [entity_id]
    yield store
    # Cleanup
    config.state_store["entities"].pop(entity_id, None)
    config.state_store["known_entities"] = []


# ── Minimal HA attribute payload (mimics a real SmartPI entity) ───────────────

MINIMAL_HA_ATTRS = {
    "current_temperature": 19.5,
    "temperature": 21.0,
    "hvac_action": "heating",
    "specific_states": {
        "ext_current_temperature": 5.0,
        "smart_pi": {
            "Kp": 0.5,
            "Ki": 0.1,
            "error": -1.5,
            "error_p": -1.5,
            "u_pi": 0.3,
            "u_applied": 0.25,
            "u_ff_eff": 0.05,
            "u_ff1": 0.18,
            "u_ff2": 0.04,
            "u_ff_final": 0.22,
            "u_ff3": -0.02,
            "u_db_nominal": 0.22,
            "u_hold": 0.21,
            "delta_hold": 0.02,
            "ff2_authority": 0.03,
            "ff2_frozen": False,
            "ff2_freeze_reason": "none",
            "u_hold_emp": 0.2,
            "u_hold_meas": 0.22,
            "hold_confidence": 0.82,
            "governance_regime": "normal",
            "phase": "running",
            "ff_reason": "ff_active",
            "ff3_enabled": True,
            "ff3_reason_disabled": "none",
            "ff3_selected_candidate": 0.2,
            "ff3_horizon_cycles": 2,
            "ff3_twin_usable": True,
            "deadband_power_source": "ff_plus_pi",
            "a": 0.8,
            "b": 0.2,
            "bootstrap_progress": 42.0,
            "bootstrap_state": "learning",
            "a_drift_state": "stable",
            "b_drift_state": "watch",
            "a_drift_buffer_count": 3,
            "b_drift_buffer_count": 4,
            "a_drift_last_reason": "ok",
            "b_drift_last_reason": "variance",
            "sensor_temperature": 19.5,
            "t_int_raw": 19.5,
            "t_int_lp": 19.45,
            "t_int_clean": 19.4,
            "sigma_t_int": 0.031,
            "adaptive_tint_update": True,
            "adaptive_tint_hold_duration_s": 120.0,
            "on_percent": 0.22,
            "calculated_on_percent": 0.24,
            "committed_on_percent": 0.22,
            "setpoint_servo_active": True,
            "setpoint_servo_phase": "landing",
            "setpoint_servo_step_amplitude": 0.6,
            "setpoint_servo_landing_zone": 0.25,
            "twin_status": "ok",
            "pred": {
                "twin_T_hat": 19.8,
                "twin_rmse_30": 0.12,
                "twin_innovation": 0.03,
                "eta_heat_100_s": 1800,
                "twin_T_steady_reliable": True,
                "twin_T_steady_max": 21.4,
                "twin_setpoint_reachable_max": True,
                "twin_bias_warning": False,
                "twin_reset_count": 1,
                "eta_u": 0.68,
            },
        },
    },
    "configuration": {
        "minimal_activation_delay_sec": 60,
        "minimal_deactivation_delay_sec": 120,
    },
}
