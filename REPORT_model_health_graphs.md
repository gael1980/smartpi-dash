# REPORT — Santé Modèle Graphs Extension

## Files changed
- `templates/dashboard.html`
- `transforms.py`

## What was implemented

### 1) Two separate 12h charts in **Santé Modèle**
- Added a dedicated chart for `a` (`a_attr`, optional `a_ema`) in the Santé Modèle tab.
- Added a dedicated chart for `b` (`b_attr`, optional `b_ema`) in the Santé Modèle tab.
- The charts are separated (not combined).
- Optional EMA/filtered series is shown only if data is present in history.

### 2) One 3h diagnostic chart in **Santé Modèle**
- Added a diagnostic chart over last 3h with:
  - Primary series: `T_int` (`t_in` history field).
  - Event overlays (only when detected):
    - rising setpoint event: `a_attr`
    - falling setpoint event: `b_attr`
    - placeholders for `a_recomputed` / `b_recomputed` are present, but disabled (see recomputation section).
- Added an explicit UI banner when recomputation cannot be done safely from available sources.
- Added diagnostic metadata panel explaining observed cadence, step detection window, debounce rule, and detected events.

### 3) History payload extension for model slopes
- Extended history snapshots to include:
  - `a`, `b`
  - optional `a_ema`, `b_ema`
- Added flatten mappings for common optional filtered keys (`a_ema`, `b_ema`, `a_filtered`, `b_filtered`, `a_filter`, `b_filter`, `a_filt`, `b_filt`) when provided by SmartPI attributes.

### 4) Deterministic fixture
- Added a deterministic in-browser fixture (`runModelHealthDiagnosticFixture`) that validates rising/falling setpoint step detection logic on a mocked short time series.

## Event detection details (exact)

Implemented in `templates/dashboard.html` (`detectSetpointStepEvents`):
- Thresholds:
  - Rising step: `Δsetpoint >= +1.0°C`
  - Falling step: `Δsetpoint <= -1.0°C`
- Detection window (`shortWindowSec`):
  - `shortWindowSec = clamp(3 * cadenceSec, 2min, 10min)`
  - `cadenceSec` is measured from observed history (median inter-sample interval).
- Event window (`W`):
  - `W = eventWindowSec = clamp(30 * cadenceSec, 15min, 45min)`
  - Rationale: 30 observed samples, derived from measured dashboard cadence.
- Debounce:
  - if multiple same-direction steps happen within `W`, keep the latest one (deterministic rule).

## Recomputation status (`a_recomputed_from_history`, `b_recomputed_from_history`)

### Status
- **Not implemented (disabled) with explicit UI banner.**

### Why
- Source-of-truth estimator implementation is **not present** in this repository.
- The repository references the estimator as external SmartPI core code (`learning.py`) in the diagram/tooltips, but does not include executable estimator logic here.
- Therefore `a_recomputed_from_history` / `b_recomputed_from_history` are **cannot be computed from available sources** in this repo without inventing model logic.

### Source references used
- Attribute flattening/source in this repo:
  - [`transforms.py` (flatten from `specific_states.smart_pi`)](transforms.py#L103)
  - [`transforms.py` (`a`/`b` mapping)](transforms.py#L149)
- History transform path:
  - [`app.py` (`/api/ha-history` -> `snapshot_for_history`)](app.py#L138)
  - [`transforms.py` (`snapshot_for_history`)](transforms.py#L353)
- External estimator reference (non-executable in this repo):
  - [`static/smartpi_block_diagram_v2.html` (`ABEstimator — ... (learning.py)`)](static/smartpi_block_diagram_v2.html#L609)
  - [`static/smartpi_block_diagram_v2.html` (`DeadTimeEstimator — ... (learning.py)`)](static/smartpi_block_diagram_v2.html#L615)

Because the estimator source-of-truth is unavailable in this codebase, recomputation cannot be made reproducible here without inventing or approximating logic, which was intentionally avoided.

## Limitations / assumptions
- If HA history/in-memory history has gaps, overlay windows may be sparse.
- EMA/filtered slope series are displayed only when those fields are actually exposed in attributes/history.
- Recomputed series are intentionally disabled until source-of-truth estimator code is available in this repo.
- Diagnostic logic is observation-based only (no model inversion shortcuts).

## Manual UI validation
1. Run app (`uv run app.py`) and open dashboard.
2. Open **🩺 Santé Modèle**.
3. Validate chart A (12h):
   - `a_attr` visible when `a` is present.
   - `a_ema` appears only if corresponding filtered/EMA data exists.
4. Validate chart B (12h):
   - `b_attr` visible when `b` is present.
   - `b_ema` appears only if corresponding filtered/EMA data exists.
5. Validate diagnostic chart (3h):
   - `T_int` always visible when temperature history exists.
   - on setpoint rise >= +1.0°C, `a_attr` overlay appears in event window.
   - on setpoint fall <= -1.0°C, `b_attr` overlay appears in event window.
   - recomputation banner is visible and explains why `a_recomputed`/`b_recomputed` are unavailable.
6. Optionally trigger setpoint steps in HA and confirm event lines/labels update accordingly.
