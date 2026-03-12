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
            "error_p": -1.5,
            "u_pi": 0.3,
            "u_applied": 0.25,
            "u_ff_eff": 0.05,
            "governance_regime": "normal",
            "phase": "running",
            "ff_reason": "ff_active",
            "a": 0.8,
            "b": 0.2,
            "pred": {
                "twin_T_hat": 19.8,
                "twin_rmse_30": 0.12,
                "twin_innovation": 0.03,
                "eta_heat_100_s": 1800,
            },
        },
    },
    "configuration": {
        "minimal_activation_delay_sec": 60,
        "minimal_deactivation_delay_sec": 120,
    },
}
