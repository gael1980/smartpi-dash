# REPORT — A/B Learning Timeline Diagnostics

## Files changed
- `templates/dashboard.html`
- `transforms.py`

## What was added
- New panel in **Santé Modèle**: **"Timeline apprentissage (12h)"**.
- Timeline chart (uPlot) with 4 rows/signals:
  - `OK events`
  - `SKIP events`
  - `Deadtime window` (band)
  - `Saturation` (band)
- Additional marker overlays on the OK row:
  - `A appris` (delta on `learn_ok_count_a`)
  - `B appris` (delta on `learn_ok_count_b`)
- Context tiles near timeline:
  - `learn_ok_count_a`
  - `learn_ok_count_b`
  - `deadtime_skip_count_a`
  - `deadtime_skip_count_b`
- "Top raisons de skip (12h)" list (top 5), with grouping mode toggle:
  - `prefix` (before `:`)
  - `exact`

## Event reconstruction logic (counter deltas)
Per history sample `i` (12h window):
- `ok_delta = max(0, learn_ok_count[i] - learn_ok_count[i-1])`
- `skip_delta = max(0, learn_skip_count[i] - learn_skip_count[i-1])`
- `ok_a_delta = max(0, learn_ok_count_a[i] - learn_ok_count_a[i-1])`
- `ok_b_delta = max(0, learn_ok_count_b[i] - learn_ok_count_b[i-1])`

Interpretation:
- `ok_delta > 0` => one OK marker at `t_i` with multiplicity `xN`
- `skip_delta > 0` => one SKIP marker at `t_i` with multiplicity `xN`
- `ok_a_delta > 0` => one `A appris` marker at `t_i` (with `xN`)
- `ok_b_delta > 0` => one `B appris` marker at `t_i` (with `xN`)

Both may exist at same timestamp; both are displayed on separate rows.

## Reset handling
Helper rule used:
- If `curr` or `prev` is null => delta `0`
- If `curr < prev` => delta `0` and counter-reset annotation

Resets are counted and shown in timeline metadata.

## Skip reasons counting
Reasons are counted **only** on timestamps where `skip_delta > 0`.
Count contribution is weighted by delta (`+skip_delta`).

Grouping:
- `prefix` mode: key is prefix before `:`
- `exact` mode: full reason string

## A/B tag on skip events
A/B tag is added only when reason text explicitly indicates A or B (regex on reason text).
If no explicit hint is found, no tag is added.

## Data used from history
The timeline uses observed history fields when available:
- `learn_ok_count`
- `learn_skip_count`
- `learn_last_reason`
- `deadtime_state`
- `in_deadtime_window`
- `sat`
- `u_applied` (available in snapshot for context; not mandatory for row rendering)
- `regime` (available in snapshot for context)
- `deadtime_skip_count_a`
- `deadtime_skip_count_b`

## Limitations
- This is reconstructed from sampled snapshots, not native per-cycle event logs.
- If sampling cadence is coarse/irregular, multiple events may merge at a single timestamp.
- If counters reset between samples, exact event attribution before reset is not recoverable.
- If `learn_last_reason` is missing/null at skip timestamps, reason appears as `unknown`.
- Tooltip detail is constrained by the chart legend/hover model (uPlot); details are summarized there and complemented by the metadata block below the chart.
