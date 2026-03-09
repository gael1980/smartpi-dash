# CLAUDE.md — SmartPI Dashboard

AI assistant guide for the `smartpi-dash` codebase. Read this before making changes.

---

## Project Overview

**SmartPI Dashboard** is a real-time monitoring and diagnostics web dashboard for the [Versatile Thermostat](https://github.com/jmcollin78/versatile_thermostat) SmartPI controller running under Home Assistant. It exposes grouped SmartPI attributes (PI regulation, thermal model, feedforward, calibration, etc.) as interactive charts, live SVG block diagrams, alerts, and performance analytics.

- **Target environment:** Edge devices (Raspberry Pi, local server) running Home Assistant
- **Language:** Python (backend) + vanilla HTML/CSS/JavaScript (frontend)
- **No build tools required.** The frontend is a single HTML file with bundled assets.

---

## Repository Structure

```
smartpi-dash/
├── app.py                  # Flask application, all HTTP routes, rate limiting, security headers
├── config.py               # App config, shared in-memory state store, HA token check
├── ha_client.py            # Home Assistant REST API client (entity discovery, state, history)
├── ws_listener.py          # Async WebSocket listener for real-time HA state changes
├── transforms.py           # Data flattening, grouping, and snapshot logic
├── import.py               # Utility: migrate Claude Code config → ChatGPT project files
├── setup_diagram.py        # Build helper: extracts SVG from HTML block diagram source
├── mcp.json                # MCP server configuration (CodeGraphContext)
├── pyproject.toml          # Python project metadata (dependencies, version)
├── requirements.txt        # Pip-compatible dependency list (kept in sync with pyproject.toml)
├── .env.example            # Environment variable template
├── REPORT_ab_diagnostics.md        # Analysis report: a/b diagnostics feature
├── REPORT_model_health_graphs.md   # Analysis report: model health graphs feature
├── templates/
│   └── dashboard.html      # Single-file SPA: HTML + embedded CSS + embedded JavaScript
└── static/
    ├── block_diagram.svg               # Interactive SVG (extracted by setup_diagram.py)
    ├── smartpi_block_diagram.html      # Block diagram source v1
    ├── smartpi_block_diagram_v2.html   # Block diagram source v2 (current)
    ├── uPlot.iife.min.js               # Bundled charting library (do not edit)
    └── uPlot.min.css                   # uPlot styles (do not edit)
```

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend runtime | Python ≥ 3.10 |
| Web framework | Flask ≥ 3.0 |
| Rate limiting | `flask-limiter` ≥ 3.5 (in-memory, 200 req/hour default) |
| Real-time HA events | `websockets` ≥ 12.0 (async, background thread) |
| HA REST API | `requests` ≥ 2.31 |
| Environment config | `python-dotenv` ≥ 1.0 |
| Package manager | **`uv`** (preferred over pip/pip3) |
| Frontend | Vanilla JS, HTML5, CSS3 — no framework, no build step |
| Charts | uPlot (bundled in `static/`) |
| Fonts | IBM Plex Sans, JetBrains Mono (Google Fonts CDN) |

---

## Environment Configuration

Copy `.env.example` to `.env` and fill in values:

```env
HA_URL=http://homeassistant.local:8123      # Home Assistant server URL
HA_TOKEN=eyJhbGciOi...                      # Long-lived access token
CLIMATE_ENTITY=climate.thermostat           # Default SmartPI entity
FLASK_PORT=5000                             # HTTP port
FLASK_HOST=127.0.0.1                        # Bind address (default: 127.0.0.1)
FLASK_SECRET_KEY=<random>                   # Auto-generated if absent
```

The `.env` file is gitignored — never commit credentials. `config.py` emits a security warning at startup if `.env` is group/world-readable or if `HA_URL` uses plain HTTP over a non-localhost address.

---

## Development Workflow

### Setup

```bash
# Install uv if needed
curl -Lsf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv sync

# Copy and configure environment
cp .env.example .env
# Edit .env with your HA_URL and HA_TOKEN

# Extract SVG block diagram from HTML source (required first time)
uv run setup_diagram.py

# Start the dashboard
uv run app.py
```

### Running

```bash
uv run app.py           # Starts Flask dev server on FLASK_HOST:FLASK_PORT (default 127.0.0.1:5000)
```

Visit `http://localhost:5000` in your browser.

### No Tests, No Linter

There is currently **no test suite and no linter configuration**. When adding tests or linting, consider:
- **pytest** for unit tests
- **ruff** for linting/formatting (compatible with uv)

Do not introduce Jest, Node, or npm unless explicitly requested.

---

## Architecture

### Data Flow

```
Home Assistant WebSocket
  │  state_changed events
  ▼
ws_listener.py (_ws_listener async loop)
  │  updates
  ▼
config.state_store["entities"][entity_id]
  │  dict with "climate", "attributes", "sensors", "history"
  ▼
Flask routes (app.py)  ← HTTP GET from browser
  │  JSON responses (with ETag caching on /api/state)
  ▼
dashboard.html (JavaScript SPA)
  │  renders charts, SVG overlays, metric cards
  ▼
User browser
```

### Threading Model

- **Main thread:** Flask HTTP server (synchronous)
- **Background daemon thread:** `ws_listener.start_ws_thread()` runs an `asyncio` event loop for the HA WebSocket
- **Shared state:** `state_store` dict in `config.py` — thread-safe for simple reads/writes under Python's GIL

### Module Responsibilities

| File | Responsibility |
|------|---------------|
| `app.py` | HTTP routing, rate limiting, security headers middleware, JSON error handling |
| `config.py` | Centralized `state_store`, config loading, HA token validation, `get_entity_store()` helper |
| `ha_client.py` | REST calls to HA (state, history, entity discovery) with 60s TTL cache |
| `ws_listener.py` | Async WS auth, subscription, event handling, auto-reconnect |
| `transforms.py` | `flatten_smartpi_attrs()`, `extract_smartpi_data()`, `snapshot_for_history()`, `SMARTPI_GROUPS` |
| `setup_diagram.py` | One-off build step: reads `smartpi_block_diagram_v2.html`, writes `static/block_diagram.svg` |
| `import.py` | Standalone utility: reads `CLAUDE.md` + `.claude/skills/` and writes ChatGPT-compatible project files to `.ai/chatgpt/` |

---

## REST API

All endpoints return JSON. Error responses: `{"ok": false, "error": "message"}`.

| Endpoint | Method | Rate Limit | Query Params | Description |
|----------|--------|------------|---|---|
| `/` | GET | — | — | Renders `dashboard.html` |
| `/api/entities` | GET | 10/min | — | Discover SmartPI climate entities |
| `/api/state` | GET | 60/min | `entity_id` | Live grouped state; supports `If-None-Match` ETag |
| `/api/history` | GET | default | `entity_id` | In-memory rolling history (≤500 points) |
| `/api/ha-history` | GET | 10/min | `entity_id`, `hours` (1–168) | History from HA REST API (60s server-side cache) |
| `/api/config` | GET | default | — | Group labels, icons, and keys for the UI |
| `/api/block-diagram` | GET | default | — | SVG block metadata (block positions, labels) |
| `/health` | GET | exempt | — | Health check: `{"ok": true, "connected": bool}` |

**Default rate limit:** 200 requests per hour per IP (via `flask-limiter`).

**Security:** Entity IDs are validated against `^[a-z_]+\.[a-z0-9_-]+$` before use (SSRF prevention).

---

## Data Models

### state_store layout

```python
state_store = {
    "entities": {
        "climate.thermostat_name": {
            "climate": {...},        # Full raw HA state object
            "attributes": {...},     # Flattened SmartPI attribute dict
            "sensors": {...},        # Associated HA sensor entities
            "last_update": "ISO",   # From HA last_updated (UTC)
            "history": deque(maxlen=500)  # Rolling snapshots
        }
    },
    "connected": bool,           # WebSocket connected? (not "ha_connected")
    "known_entities": [str],     # Discovered SmartPI entity IDs
}
```

**Note:** The key is `"connected"` (not `"ha_connected"`). The `get_entity_store(entity_id)` helper in `config.py` safely initializes a new entity slot if it doesn't exist.

### History Snapshot (one entry per WS event)

~45 fields including: `ts`, `t_in`, `t_target`, `t_ext`, `on_percent`, `u_applied`, `u_ff`, `u_pi`, `u_cmd`, `u_limited`, `u_p`, `u_i`, `twin_t_hat`, `twin_innovation`, `twin_d_hat`, `twin_rmse`, `twin_cusum`, `regime`, `phase`, `ff_gate`, `ff_scale`, `ff_k_ff`, `autocalib_state`, `cycle_state`, `guard_cut`, `error_p`, `kp`, `ki`, `deadtime_heat_s`, `deadtime_cool_s`, `a`, `b`, `a_ema`, `b_ema`, `near_band_above`, `near_band_below`, `in_deadband`, `learn_last_reason`, `learn_ok_count`, `learn_skip_count`, `deadtime_state`, `in_deadtime_window`, `sat`, `deadtime_skip_count_a`, `deadtime_skip_count_b`, `learn_ok_count_a`, `learn_ok_count_b`, `sensor_temperature`.

---

## SmartPI Data Groups

Defined in `transforms.py` as `SMARTPI_GROUPS`. Each group has `label`, `icon`, and `keys` (attribute names). An automatic `"extras"` group (`📋 Autres attributs SmartPI`) is also returned for any unmapped `smartpi_*` attributes found in the entity.

| Icon | Group ID | Label | Description |
|------|----------|-------|-------------|
| ⚡ | `regulation` | Régulation PI | Kp, Ki, errors, u_components |
| 🏠 | `model` | Modèle Thermique | a, b, τ, deadtimes, learn counters |
| 🔬 | `twin` | Thermal Twin | T̂, innovation, RMSE, CUSUM, ETA |
| 🛡️ | `governance` | Gouvernance & Sécurité | regime, phase, guards, integral state |
| 🎯 | `feedforward` | Feedforward | enabled, K_ff, u_ff, warmup, gate, scale |
| 🔧 | `calibration` | Calibration & AutoCalib | calibration_state, autocalib flags, retry count, snapshot age |
| 📐 | `setpoint_filter` | Filtre de Consigne | SP_brut, SP_for_P, mode, tau |
| ⏱️ | `cycle` | Cycle PWM | min cycle, state, min_on/off, rate limit |

---

## Frontend Architecture (`templates/dashboard.html`)

The entire frontend is a single ~7,200-line HTML file with embedded CSS and JavaScript. **No build step.**

### Structure

1. **HTML** (~1,600 lines) — Topbar, hero metrics bar, 12-tab navigation, tab panels
2. **CSS** (~600 lines) — CSS variables (dark theme + SCADA industrial theme), component styles, animations, responsive 768px breakpoint
3. **JavaScript** (~5,000 lines) — State management, API polling, chart rendering, SVG interaction, SCADA synoptic

### 12 Dashboard Tabs

| Tab Button Label | `data-tab` id | Content |
|-----|------|---------|
| 📊 Données | `tab-data` | Grouped attribute cards |
| 📈 Historique | `tab-charts` | uPlot time-series charts (1–48h range) |
| 🔄 Schéma Bloc | `tab-diagram` | Interactive SVG block diagram with live overlays |
| 🔗 Chaîne U | `tab-debug-chain` | Waterfall + breakdown + time-series for control output |
| 🎯 Feedforward | `tab-feedforward` | FF pipeline steps, K_ff calculation, charts |
| 🩺 Santé Modèle | `tab-model-health` | Model reliability scores, learning progress, a/b drift diagnostics |
| 🎛️ Tuning Assistant | `tab-tuning` | Tuning readiness gauge, PI params with reliability badges, observability sparklines (RMSE, innovation, CUSUM), theoretical PI references (SIMC/IMC), model maturity, stability window, recent response analysis, enriched recommendations |
| 📍 Événements | `tab-events` | Filtered timeline of state transitions |
| 🚨 Alertes | `tab-alerts` | 9 configurable threshold rules (LocalStorage) |
| 🧪 Consigne vs Réalisé | `tab-perf` | Error metrics, overshoot, deadband analysis |
| 🏭 Supervision | `tab-scada` | Industrial-style SCADA synoptic with animated flow indicators |
| 🗂️ Attributs bruts | `tab-raw` | Full JSON attribute dump |

### State & Persistence

- **Global JS state object** holds current entity data, charts, and UI flags
- **Tab routing:** URL hash `#tab-data`, `#tab-charts`, etc.
- **Entity selection:** Query param `?entity_id=climate.xyz`
- **Alert thresholds:** Persisted in `localStorage`

### CSS Theme Variables

Two themes are defined at `:root`:
- **Dark dashboard theme:** `--bg`, `--bg-panel`, `--bg-block`, `--bg-card`, `--border`, `--text`, `--accent-*`, `--signal-*`, `--glow-*`
- **SCADA industrial theme:** `--sc-bg`, `--sc-bg-panel`, `--sc-flow-speed`

Always use CSS variables — never hardcode color values.

---

## Security Conventions

The following security practices are in place — maintain them:

1. **CSP headers** set in `app.py` `@app.after_request`
2. **X-Content-Type-Options: nosniff** and **X-Frame-Options: DENY**
3. **X-XSS-Protection: 1; mode=block**
4. **Referrer-Policy: strict-origin-when-cross-origin**
5. **Strict-Transport-Security** (HTTPS connections only, max-age=31536000)
6. **Permissions-Policy** (disables camera, microphone, geolocation)
7. **Entity ID regex validation** `^[a-z_]+\.[a-z0-9_-]+$` before passing to HA API — do not bypass
8. **HA token via `.env`** — never hardcode or log
9. **Hours clamped 1–168** for HA history requests (prevents large response attacks)
10. **Auto-generated `FLASK_SECRET_KEY`** if not set
11. **FLASK_DEBUG is forbidden** — startup aborts if `FLASK_DEBUG=1` is set (Werkzeug interactive debugger = RCE risk)
12. **Rate limiting** via `flask-limiter` (200 req/hour default, stricter on heavy endpoints)
13. **`/health` is rate-limit exempt** — safe for load-balancer probes

When adding new API endpoints, always validate and sanitize query parameters. Follow the existing pattern in `app.py`.

---

## Key Conventions

### Python

- Use `uv` for all package management (`uv add`, `uv sync`), not pip
- Keep `requirements.txt` in sync with `pyproject.toml` if modified
- Module-level state goes in `config.py`, not scattered across modules
- Use `get_entity_store(entity_id)` from `config.py` to safely access/initialize entity slots
- Async code (WebSocket) runs isolated in its own thread with its own `asyncio` loop
- Log using `logging` (configured in `config.py`) — not `print()`
- Response format: `{"ok": True, ...payload}` or `{"ok": False, "error": "..."}`, HTTP 400 on error
- New endpoints that are resource-intensive should use `@limiter.limit("N/minute")`

### Frontend

- **Do not introduce a JS framework** (React, Vue, etc.) or npm — this is intentional
- **Do not add a build step** unless the project explicitly migrates to one
- New tabs follow the existing pattern: add HTML panel, add tab button, add JS section
- Charts use uPlot — do not add Chart.js or other chart libs
- CSS variables are defined at `:root` — use them, don't hardcode color values
- All user-configurable state that should survive refresh goes to `localStorage`

### Git

- Use conventional commits: `feat:`, `fix:`, `docs:`, `style:`, `refactor:`
- Commit messages in English
- Branch names follow the `claude/<description>` convention for AI-generated work

---

## Dependency Management

```bash
# Add a new dependency
uv add <package>

# Sync after pulling changes
uv sync

# Export pip-compatible requirements (keep in sync)
uv pip compile pyproject.toml -o requirements.txt
```

---

## Common Tasks

### Add a new API endpoint

1. Add route function in `app.py` following existing patterns
2. Validate all query parameters with regex or type casting
3. Add `@limiter.limit("N/minute")` for endpoints that hit HA or do heavy work
4. Return `{"ok": True, ...}` on success, `{"ok": False, "error": "..."}` with HTTP 400 on failure
5. Document the endpoint in the API table in this file

### Add a new SmartPI data group

1. Add an entry to `SMARTPI_GROUPS` in `transforms.py`
2. Ensure the attribute keys exist in the HA entity's `specific_states` namespace
3. The frontend will automatically discover the group via `/api/config`

### Add a new dashboard tab

1. Add a `<button class="tab-btn" data-tab="tab-name">` in the tab navigation
2. Add a `<div id="tab-name" class="tab-panel">` with content
3. Add the corresponding JavaScript section in the script block
4. Handle tab activation in the existing `switchTab()` function

### Update the block diagram SVG

1. Edit `static/smartpi_block_diagram_v2.html`
2. Run `uv run setup_diagram.py` to regenerate `static/block_diagram.svg`
3. Commit both files

### Migrate config to ChatGPT

`import.py` is a standalone utility (no extra deps beyond stdlib) that reads `CLAUDE.md` and `.claude/skills/*.md`, then writes a ChatGPT-compatible project package to `.ai/chatgpt/`:

```bash
python import.py --repo . --out .ai/chatgpt
```

---

## What AI Assistants Should Avoid

- **Do not add npm, Node.js, or any JS build toolchain** unless explicitly asked
- **Do not introduce a database** — the in-memory store is intentional for simplicity
- **Do not bypass security validations** (entity ID regex, hours clamping, CSP headers, rate limits)
- **Do not commit `.env`** — it contains credentials
- **Do not use `print()` for logging** — use the `logging` module
- **Do not modify bundled libraries** (`uPlot.iife.min.js`, `uPlot.min.css`)
- **Do not split `dashboard.html`** into a multi-file frontend without explicit direction — the single-file approach is intentional for easy deployment
- **Do not enable FLASK_DEBUG** — it is explicitly blocked at startup
- **Do not use `"ha_connected"` as a state_store key** — the correct key is `"connected"`
