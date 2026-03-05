"""SmartPI domain constants and pure data transforms."""

from datetime import datetime, timezone

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
            "smartpi_learn_ok_count", "smartpi_learn_skip_count",
            "smartpi_deadtime_state", "smartpi_in_deadtime_window",
            "smartpi_deadtime_skip_count_a", "smartpi_deadtime_skip_count_b",
            "smartpi_learn_last_reason",
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

# Flattened set of all known SmartPI attribute keys
ALL_SMARTPI_KEYS = set()
for _grp in SMARTPI_GROUPS.values():
    ALL_SMARTPI_KEYS.update(_grp["keys"])


def _first_not_none(*values):
    """Return the first value that is not None."""
    for v in values:
        if v is not None:
            return v
    return None


def flatten_smartpi_attrs(raw_attrs: dict) -> dict:
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
        "sensor_temperature": "smartpi_sensor_temperature",
        "a": "smartpi_a",
        "b": "smartpi_b",
        "a_ema": "smartpi_a_ema",
        "b_ema": "smartpi_b_ema",
        "a_filtered": "smartpi_a_filtered",
        "b_filtered": "smartpi_b_filtered",
        "a_filter": "smartpi_a_filter",
        "b_filter": "smartpi_b_filter",
        "a_filt": "smartpi_a_filt",
        "b_filt": "smartpi_b_filt",
        "tau_min": "smartpi_tau_min",
        "tau_reliable": "smartpi_tau_reliable",
        "deadtime_heat_s": "smartpi_deadtime_heat_s",
        "deadtime_cool_s": "smartpi_deadtime_cool_s",
        "deadtime_heat_reliable": "smartpi_deadtime_heat_reliable",
        "deadtime_cool_reliable": "smartpi_deadtime_cool_reliable",
        "learn_ok_count_a": "smartpi_learn_ok_count_a",
        "learn_ok_count_b": "smartpi_learn_ok_count_b",
        "learn_ok_count": "smartpi_learn_ok_count",
        "learn_skip_count": "smartpi_learn_skip_count",
        "deadtime_state": "smartpi_deadtime_state",
        "in_deadtime_window": "smartpi_in_deadtime_window",
        "deadtime_skip_count_a": "smartpi_deadtime_skip_count_a",
        "deadtime_skip_count_b": "smartpi_deadtime_skip_count_b",
        "learn_last_reason": "smartpi_learn_last_reason",
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

    # Compatibility fallbacks for SmartPI variants
    if flat.get("smartpi_regime") is None:
        flat["smartpi_regime"] = _first_not_none(
            spi.get("regime"),
            spi.get("governance_mode"),
            spi.get("mode"),
        )
    if flat.get("smartpi_phase") is None:
        flat["smartpi_phase"] = _first_not_none(
            spi.get("governance_phase"),
            spi.get("state_phase"),
        )

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
    cfg = raw_attrs.get("configuration", {})
    if isinstance(cfg, dict):
        if cfg.get("minimal_activation_delay_sec") is not None:
            flat["smartpi_min_on_s"] = cfg["minimal_activation_delay_sec"]
        if cfg.get("minimal_deactivation_delay_sec") is not None:
            flat["smartpi_min_off_s"] = cfg["minimal_deactivation_delay_sec"]

    return flat


def extract_smartpi_data(attrs: dict) -> dict:
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


def ensure_utc_iso(ts_str: str | None) -> str | None:
    """Ensure an ISO timestamp has explicit UTC offset for correct JS parsing.

    Home Assistant may send naive ISO strings (no timezone offset).
    JavaScript new Date() treats these as local time, causing display errors.
    """
    if not ts_str:
        return ts_str
    # Python 3.10 fromisoformat() doesn't support 'Z', normalize first
    normalized = ts_str.replace("Z", "+00:00") if ts_str.endswith("Z") else ts_str
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError):
        return ts_str


def _extract_optional_slope(attrs: dict, name: str):
    """Extract optional filtered/EMA variants for slope-like model parameters."""
    candidates = [
        f"smartpi_{name}_ema",
        f"smartpi_{name}_filtered",
        f"smartpi_{name}_filter",
        f"smartpi_{name}_filt",
        f"{name}_ema",
        f"{name}_filtered",
        f"{name}_filter",
        f"{name}_filt",
    ]
    for key in candidates:
        val = attrs.get(key)
        if val is not None:
            return val

    specific = attrs.get("specific_states", {})
    if isinstance(specific, dict):
        spi = specific.get("smart_pi", {})
        if isinstance(spi, dict):
            nested_candidates = [
                f"{name}_ema",
                f"{name}_filtered",
                f"{name}_filter",
                f"{name}_filt",
            ]
            for key in nested_candidates:
                val = spi.get(key)
                if val is not None:
                    return val
    return None


def snapshot_for_history(attrs: dict) -> dict:
    """Create a compact snapshot for the rolling history."""
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "sensor_temperature": attrs.get("smartpi_sensor_temperature"),
        "t_in": _first_not_none(attrs.get("smartpi_sensor_temperature"), attrs.get("current_temperature")),
        "t_target": _first_not_none(
            attrs.get("temperature"),
            attrs.get("target_temperature"),
            attrs.get("smartpi_sp_brut"),
            attrs.get("smartpi_sp_for_p"),
        ),
        "t_ext": _first_not_none(attrs.get("smartpi_t_ext"), attrs.get("current_external_temperature")),
        "on_percent": attrs.get("on_percent"),
        "u_applied": attrs.get("smartpi_u_applied"),
        "u_ff": _first_not_none(attrs.get("smartpi_ff_u_ff"), attrs.get("smartpi_u_ff")),
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
        "regime": _first_not_none(attrs.get("smartpi_regime"), attrs.get("governance_regime"), attrs.get("regime")),
        "phase": _first_not_none(attrs.get("smartpi_phase"), attrs.get("phase")),
        "deadtime_heat_s": attrs.get("smartpi_deadtime_heat_s"),
        "deadtime_cool_s": attrs.get("smartpi_deadtime_cool_s"),
        "a": _first_not_none(attrs.get("smartpi_a"), attrs.get("a")),
        "b": _first_not_none(attrs.get("smartpi_b"), attrs.get("b")),
        "a_ema": _extract_optional_slope(attrs, "a"),
        "b_ema": _extract_optional_slope(attrs, "b"),
        "near_band_above": attrs.get("smartpi_near_band_above_deg"),
        "near_band_below": attrs.get("smartpi_near_band_below_deg"),
        "in_deadband": attrs.get("smartpi_in_deadband"),
        "ff_gate": attrs.get("smartpi_ff_gate"),
        "ff_scale": attrs.get("smartpi_ff_scale"),
        "ff_k_ff": attrs.get("smartpi_ff_k_ff"),
        "learn_last_reason": _first_not_none(
            attrs.get("smartpi_learn_last_reason"),
            attrs.get("learn_last_reason"),
        ),
        "learn_ok_count": attrs.get("smartpi_learn_ok_count"),
        "learn_skip_count": attrs.get("smartpi_learn_skip_count"),
        "deadtime_state": attrs.get("smartpi_deadtime_state"),
        "in_deadtime_window": attrs.get("smartpi_in_deadtime_window"),
        "sat": _first_not_none(attrs.get("smartpi_cycle_state"), attrs.get("cycle_state"), attrs.get("sat")),
        "deadtime_skip_count_a": attrs.get("smartpi_deadtime_skip_count_a"),
        "deadtime_skip_count_b": attrs.get("smartpi_deadtime_skip_count_b"),
        "learn_ok_count_a": attrs.get("smartpi_learn_ok_count_a"),
        "learn_ok_count_b": attrs.get("smartpi_learn_ok_count_b"),
        "autocalib_state": attrs.get("smartpi_autocalib_state"),
        "cycle_state": attrs.get("smartpi_cycle_state"),
        "guard_cut": attrs.get("smartpi_guard_cut_active"),
        "twin_rmse": attrs.get("smartpi_twin_rmse"),
        "twin_cusum": attrs.get("smartpi_twin_cusum"),
    }
