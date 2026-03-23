"""Tests for transforms.py — pure data functions."""

import pytest
from transforms import (
    flatten_smartpi_attrs,
    extract_smartpi_data,
    snapshot_for_history,
    ensure_utc_iso,
    SMARTPI_GROUPS,
    ALL_SMARTPI_KEYS,
    _first_not_none,
)
from tests.conftest import MINIMAL_HA_ATTRS


# ── _first_not_none ───────────────────────────────────────────────────────────

class TestFirstNotNone:
    def test_returns_first_non_none(self):
        assert _first_not_none(None, None, 42) == 42

    def test_returns_first_when_all_set(self):
        assert _first_not_none(1, 2, 3) == 1

    def test_returns_none_when_all_none(self):
        assert _first_not_none(None, None) is None

    def test_zero_is_valid(self):
        assert _first_not_none(None, 0, 1) == 0

    def test_false_is_valid(self):
        assert _first_not_none(None, False, True) is False

    def test_empty_string_is_valid(self):
        assert _first_not_none(None, "", "fallback") == ""


# ── ensure_utc_iso ────────────────────────────────────────────────────────────

class TestEnsureUtcIso:
    def test_none_returns_none(self):
        assert ensure_utc_iso(None) is None

    def test_empty_string_passthrough(self):
        assert ensure_utc_iso("") == ""

    def test_z_suffix_normalized(self):
        result = ensure_utc_iso("2024-01-15T10:30:00Z")
        assert result == "2024-01-15T10:30:00+00:00"

    def test_naive_timestamp_gets_utc(self):
        result = ensure_utc_iso("2024-01-15T10:30:00")
        assert "+00:00" in result

    def test_explicit_offset_preserved(self):
        ts = "2024-01-15T10:30:00+02:00"
        result = ensure_utc_iso(ts)
        assert "+02:00" in result

    def test_utc_offset_preserved(self):
        ts = "2024-01-15T10:30:00+00:00"
        result = ensure_utc_iso(ts)
        assert result == ts

    def test_invalid_returns_as_is(self):
        bad = "not-a-date"
        assert ensure_utc_iso(bad) == bad


# ── flatten_smartpi_attrs ─────────────────────────────────────────────────────

class TestFlattenSmartpiAttrs:
    def test_empty_input_returns_empty(self):
        result = flatten_smartpi_attrs({})
        assert isinstance(result, dict)

    def test_top_level_attrs_preserved(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["current_temperature"] == 19.5
        assert result["temperature"] == 21.0

    def test_kp_mapped(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_kp"] == 0.5

    def test_ki_mapped(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_ki"] == 0.1

    def test_error_p_mapped(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_error_p"] == -1.5

    def test_u_pi_mapped(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_u_pi"] == 0.3

    def test_regime_from_governance_regime(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_regime"] == "normal"

    def test_phase_mapped(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_phase"] == "running"

    def test_ext_temperature_mapped(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_t_ext"] == 5.0

    def test_ff_enabled_when_active(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_ff_enabled"] is True

    def test_ff_disabled_when_ff_none(self):
        attrs = {"specific_states": {"smart_pi": {"ff_reason": "ff_none"}}}
        result = flatten_smartpi_attrs(attrs)
        assert result["smartpi_ff_enabled"] is False

    def test_ff_disabled_when_no_ff_reason(self):
        attrs = {"specific_states": {"smart_pi": {}}}
        result = flatten_smartpi_attrs(attrs)
        assert result["smartpi_ff_enabled"] is False

    def test_ff_k_ff_computed(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert abs(result["smartpi_ff_k_ff"] - 0.2 / 0.8) < 1e-9

    def test_ff_k_ff_skipped_when_a_zero(self):
        attrs = {"specific_states": {"smart_pi": {"a": 0, "b": 0.2}}}
        result = flatten_smartpi_attrs(attrs)
        assert "smartpi_ff_k_ff" not in result

    def test_sp_brut_from_temperature(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_sp_brut"] == 21.0

    def test_min_on_from_configuration(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_min_on_s"] == 60

    def test_min_off_from_configuration(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_min_off_s"] == 120

    def test_pred_twin_t_hat(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_twin_t_hat"] == 19.8

    def test_pred_twin_rmse(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_twin_rmse"] == 0.12

    def test_pred_twin_eta_s(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_twin_eta_s"] == 1800

    def test_u_ff_alias_sync(self):
        """smartpi_ff_u_ff and smartpi_u_ff should point to the same value."""
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result.get("smartpi_ff_u_ff") == 0.05
        assert result.get("smartpi_ff_u_ff") == result.get("smartpi_u_ff")

    def test_ff_chain_compatibility_aliases_from_v3_fields(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_u_ff1"] == 0.18
        assert result["smartpi_u_ff2"] == 0.04
        assert result["smartpi_ff_u_ff_ab"] == 0.18
        assert result["smartpi_ff_u_ff_trim"] == 0.04
        assert result["smartpi_ff_u_ff_base"] == 0.18

    def test_on_percent_alias_promoted_to_top_level(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_on_percent"] == 0.22
        assert result["on_percent"] == 0.22

    def test_new_servo_and_tint_fields_are_mapped(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_setpoint_servo_phase"] == "landing"
        assert result["smartpi_t_int_clean"] == 19.4
        assert result["smartpi_sigma_t_int"] == 0.031

    def test_advanced_twin_fields_are_mapped(self):
        result = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)
        assert result["smartpi_twin_status"] == "ok"
        assert result["smartpi_twin_t_steady_max"] == 21.4
        assert result["smartpi_twin_eta_u"] == 0.68

    def test_regime_fallback_from_regime_key(self):
        attrs = {"specific_states": {"smart_pi": {"regime": "safe"}}}
        result = flatten_smartpi_attrs(attrs)
        assert result["smartpi_regime"] == "safe"

    def test_regime_fallback_from_governance_mode(self):
        attrs = {"specific_states": {"smart_pi": {"governance_mode": "boost"}}}
        result = flatten_smartpi_attrs(attrs)
        assert result["smartpi_regime"] == "boost"

    def test_specific_states_not_dict(self):
        attrs = {"specific_states": "bad_value"}
        result = flatten_smartpi_attrs(attrs)
        assert result == {"specific_states": "bad_value"}

    def test_none_values_not_mapped(self):
        """Keys with None values in spi should not be written."""
        attrs = {"specific_states": {"smart_pi": {"Kp": None}}}
        result = flatten_smartpi_attrs(attrs)
        assert "smartpi_kp" not in result


# ── extract_smartpi_data ──────────────────────────────────────────────────────

class TestExtractSmartpiData:
    def setup_method(self):
        self.attrs = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)

    def test_all_groups_present(self):
        grouped = extract_smartpi_data(self.attrs)
        for gid in SMARTPI_GROUPS:
            assert gid in grouped

    def test_group_has_label_icon_values(self):
        grouped = extract_smartpi_data(self.attrs)
        for gid, group in grouped.items():
            if gid == "extras":
                continue
            assert "label" in group
            assert "icon" in group
            assert "values" in group

    def test_known_key_in_group(self):
        grouped = extract_smartpi_data(self.attrs)
        assert grouped["regulation"]["values"]["smartpi_kp"] == 0.5

    def test_extras_group_for_unknown_keys(self):
        attrs = {**self.attrs, "smartpi_unknown_future_key": 99}
        grouped = extract_smartpi_data(attrs)
        assert "extras" in grouped
        assert grouped["extras"]["values"]["smartpi_unknown_future_key"] == 99

    def test_no_extras_when_no_unknown_keys(self):
        # Use only keys that are already in ALL_SMARTPI_KEYS (or non-smartpi)
        clean_attrs = {k: v for k, v in self.attrs.items()
                       if not k.startswith("smartpi_") or k in ALL_SMARTPI_KEYS}
        grouped = extract_smartpi_data(clean_attrs)
        assert "extras" not in grouped

    def test_values_can_be_none_for_missing_keys(self):
        grouped = extract_smartpi_data({})
        for gid in SMARTPI_GROUPS:
            for v in grouped[gid]["values"].values():
                assert v is None


# ── snapshot_for_history ──────────────────────────────────────────────────────

class TestSnapshotForHistory:
    def setup_method(self):
        self.attrs = flatten_smartpi_attrs(MINIMAL_HA_ATTRS)

    def test_snapshot_has_ts(self):
        snap = snapshot_for_history(self.attrs)
        assert "ts" in snap
        assert snap["ts"] is not None

    def test_snapshot_t_in(self):
        snap = snapshot_for_history(self.attrs)
        # smartpi_sensor_temperature is None in MINIMAL_HA_ATTRS,
        # falls back to current_temperature
        assert snap["t_in"] == 19.5

    def test_snapshot_t_target(self):
        snap = snapshot_for_history(self.attrs)
        assert snap["t_target"] == 21.0

    def test_snapshot_t_ext(self):
        snap = snapshot_for_history(self.attrs)
        assert snap["t_ext"] == 5.0

    def test_snapshot_kp(self):
        snap = snapshot_for_history(self.attrs)
        assert snap["kp"] == 0.5

    def test_snapshot_regime(self):
        snap = snapshot_for_history(self.attrs)
        assert snap["regime"] == "normal"

    def test_snapshot_twin_t_hat(self):
        snap = snapshot_for_history(self.attrs)
        assert snap["twin_t_hat"] == 19.8

    def test_snapshot_twin_eta_s(self):
        snap = snapshot_for_history(self.attrs)
        assert snap["twin_eta_s"] == 1800

    def test_snapshot_a_b(self):
        snap = snapshot_for_history(self.attrs)
        assert snap["a"] == 0.8
        assert snap["b"] == 0.2

    def test_snapshot_ff3_chain(self):
        snap = snapshot_for_history(self.attrs)
        assert snap["u_ff1"] == 0.18
        assert snap["u_ff2"] == 0.04
        assert snap["u_ff3"] == -0.02
        assert snap["u_db_nominal"] == 0.22
        assert snap["ff3_enabled"] is True

    def test_snapshot_power_and_servo_fields(self):
        snap = snapshot_for_history(self.attrs)
        assert snap["on_percent"] == 0.22
        assert snap["calculated_on_percent"] == 0.24
        assert snap["committed_on_percent"] == 0.22
        assert snap["setpoint_servo_phase"] == "landing"

    def test_snapshot_model_filter_and_drift(self):
        snap = snapshot_for_history(self.attrs)
        assert snap["t_int_clean"] == 19.4
        assert snap["sigma_t_int"] == 0.031
        assert snap["a_drift_state"] == "stable"
        assert snap["b_drift_last_reason"] == "variance"

    def test_snapshot_advanced_twin_fields(self):
        snap = snapshot_for_history(self.attrs)
        assert snap["twin_status"] == "ok"
        assert snap["twin_t_steady_max"] == 21.4
        assert snap["twin_eta_u"] == 0.68
        assert snap["twin_reset_count"] == 1

    def test_snapshot_empty_attrs(self):
        snap = snapshot_for_history({})
        assert "ts" in snap
        assert snap["t_in"] is None
        assert snap["kp"] is None

    def test_snapshot_is_dict(self):
        snap = snapshot_for_history(self.attrs)
        assert isinstance(snap, dict)

    def test_snapshot_ts_is_utc_iso(self):
        snap = snapshot_for_history(self.attrs)
        assert "+00:00" in snap["ts"] or "Z" in snap["ts"]
