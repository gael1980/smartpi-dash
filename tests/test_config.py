"""Tests for config.py — state management and validation."""

import pytest
from collections import deque
import config


class TestEntityIdRegex:
    """ENTITY_ID_RE must accept valid HA entity IDs and reject malicious ones."""

    valid = [
        "climate.thermostat",
        "climate.thermostat_cuisine",
        "climate.my-thermostat",
        "sensor.temperature_1",
        "switch.relay_01",
    ]

    invalid = [
        "",
        "climate",                    # no dot
        "Climate.thermostat",         # uppercase domain
        "climate.Thermostat",         # uppercase entity
        "climate.thermostat/../../etc/passwd",  # path traversal
        "climate.thermostat; rm -rf /",         # shell injection
        "climate.thermostat\nX-Injected: yes",  # header injection
        "../etc/passwd",
        "climate..thermostat",        # double dot
        "climate.thermostat entity",  # space
    ]

    @pytest.mark.parametrize("eid", valid)
    def test_valid_entity_id(self, eid):
        assert config.ENTITY_ID_RE.match(eid), f"Expected {eid!r} to match"

    @pytest.mark.parametrize("eid", invalid)
    def test_invalid_entity_id(self, eid):
        assert not config.ENTITY_ID_RE.match(eid), f"Expected {eid!r} to NOT match"


class TestStateStore:
    def test_state_store_has_entities(self):
        assert "entities" in config.state_store

    def test_state_store_has_connected(self):
        assert "connected" in config.state_store

    def test_state_store_connected_is_bool(self):
        assert isinstance(config.state_store["connected"], bool)

    def test_state_store_has_known_entities(self):
        assert "known_entities" in config.state_store

    def test_state_store_known_entities_is_list(self):
        assert isinstance(config.state_store["known_entities"], list)


class TestGetEntityStore:
    def teardown_method(self):
        # Remove test entities created during tests
        for key in list(config.state_store["entities"].keys()):
            if key.startswith("climate.test_"):
                del config.state_store["entities"][key]

    def test_creates_new_entity_slot(self):
        eid = "climate.test_new_entity"
        store = config.get_entity_store(eid)
        assert eid in config.state_store["entities"]

    def test_returns_same_object_on_second_call(self):
        eid = "climate.test_same_entity"
        store1 = config.get_entity_store(eid)
        store2 = config.get_entity_store(eid)
        assert store1 is store2

    def test_initial_slot_has_climate_key(self):
        store = config.get_entity_store("climate.test_slot_climate")
        assert "climate" in store

    def test_initial_slot_has_attributes_key(self):
        store = config.get_entity_store("climate.test_slot_attrs")
        assert "attributes" in store

    def test_initial_slot_has_sensors_key(self):
        store = config.get_entity_store("climate.test_slot_sensors")
        assert "sensors" in store

    def test_initial_slot_has_last_update_none(self):
        store = config.get_entity_store("climate.test_slot_lu")
        assert store["last_update"] is None

    def test_initial_slot_has_history_deque(self):
        store = config.get_entity_store("climate.test_slot_hist")
        assert isinstance(store["history"], deque)

    def test_history_deque_maxlen(self):
        store = config.get_entity_store("climate.test_slot_maxlen")
        assert store["history"].maxlen == config.MAX_HISTORY

    def test_history_maxlen_is_500(self):
        assert config.MAX_HISTORY == 500

    def test_history_deque_auto_evicts(self):
        store = config.get_entity_store("climate.test_slot_evict")
        for i in range(config.MAX_HISTORY + 10):
            store["history"].append({"ts": str(i)})
        assert len(store["history"]) == config.MAX_HISTORY

    def test_data_persists_across_calls(self):
        eid = "climate.test_persist"
        store = config.get_entity_store(eid)
        store["attributes"]["kp"] = 42
        store2 = config.get_entity_store(eid)
        assert store2["attributes"]["kp"] == 42
