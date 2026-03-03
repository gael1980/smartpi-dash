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
├── app.py                  # Flask application, all HTTP routes, security headers
├── config.py               # App config, shared in-memory state store, HA token check
├── ha_client.py            # Home Assistant REST API client (entity discovery, state, history)
├── ws_listener.py          # Async WebSocket listener for real-time HA state changes
├── transforms.py           # Data flattening, grouping, and snapshot logic
├── setup_diagram.py        # Build helper: extracts SVG from HTML block diagram source
├── pyproject.toml          # Python project metadata (dependencies, version)
├── requirements.txt        # Pip-compatible dependency list (kept in sync with pyproject.toml)
├── .env.example            # Environment variable template
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
FLASK_SECRET_KEY=<random>                   # Auto-generated if absent
```

The `.env` file is gitignored — never commit credentials.

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
uv run app.py           # Starts Flask dev server on FLASK_PORT (default 5000)
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
  │  JSON responses
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
| `app.py` | HTTP routing, security headers middleware, JSON error handling |
| `config.py` | Centralized `state_store`, config loading, HA token validation |
| `ha_client.py` | REST calls to HA (state, history, entity discovery) with 60s TTL cache |
| `ws_listener.py` | Async WS auth, subscription, event handling, auto-reconnect |
| `transforms.py` | `flatten_smartpi_attrs()`, `extract_smartpi_data()`, `snapshot_for_history()`, `SMARTPI_GROUPS` |
| `setup_diagram.py` | One-off build step: reads `smartpi_block_diagram_v2.html`, writes `static/block_diagram.svg` |

---

## REST API

All endpoints return JSON. Error responses: `{"ok": false, "error": "message"}`.

| Endpoint | Method | Query Params | Description |
|----------|--------|---|---|
| `/` | GET | — | Renders `dashboard.html` |
| `/api/entities` | GET | — | Discover SmartPI climate entities |
| `/api/state` | GET | `entity_id` | Live grouped state for one entity |
| `/api/history` | GET | `entity_id` | In-memory rolling history (≤500 points) |
| `/api/ha-history` | GET | `entity_id`, `hours` (1–168) | History from HA REST API |
| `/api/config` | GET | — | Group labels, icons, and keys for the UI |
| `/api/block-diagram` | GET | — | SVG block metadata (block positions, labels) |

**Security:** Entity IDs are validated against `^[a-z_]+\.[a-z0-9_]+$` before use (SSRF prevention).

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
            "last_update": "ISO",   # From HA last_changed
            "history": [...]         # Rolling list of snapshots (max 500)
        }
    },
    "config": {"climate_entity": str},
    "ha_connected": bool
}
```

### History Snapshot (one entry per WS event)

~30 fields including: `ts`, `t_in`, `t_target`, `t_ext`, `on_percent`, `u_applied`, `u_ff`, `u_pi`, `u_cmd`, `twin_t_hat`, `twin_innovation`, `twin_d_hat`, `regime`, `phase`, `ff_gate`, `autocalib_state`, `cycle_state`, and more.

---

## SmartPI Data Groups

Defined in `transforms.py` as `SMARTPI_GROUPS`. Each group has `label`, `icon`, and `keys` (attribute names):

| Icon | Group | Description |
|------|-------|-------------|
| ⚡ | Régulation PI | Kp, Ki, errors, u_components |
| 🏠 | Modèle Thermique | a, b, τ, deadtimes, learn counters |
| 🔬 | Thermal Twin | T̂, innovation, RMSE, CUSUM, ETA |
| 🛡️ | Gouvernance | regime, phase, guards, integral state |
| 🎯 | Feedforward | enabled, K_ff, u_ff, warmup, gate |
| 🔧 | Calibration | AutoCalib state, degradation flags, retry count |
| 📐 | Filtre Consigne | SP_brut, SP_for_P, mode, tau |
| ⏱️ | Cycle PWM | min cycle, state, min_on/off, rate limit |

---

## Frontend Architecture (`templates/dashboard.html`)

The entire frontend is a single ~3,500-line HTML file with embedded CSS and JavaScript. **No build step.**

### Structure

1. **HTML** (~400 lines) — Topbar, hero metrics bar, 10-tab navigation, tab panels
2. **CSS** (~500 lines) — CSS variables (dark theme), component styles, animations, responsive 768px breakpoint
3. **JavaScript** (~2,500 lines) — State management, API polling, chart rendering, SVG interaction

### 10 Dashboard Tabs

| Tab | `id` | Content |
|-----|------|---------|
| Données | `tab-data` | Grouped attribute cards |
| Historique | `tab-history` | uPlot time-series charts (1–48h range) |
| Schéma | `tab-diagram` | Interactive SVG block diagram with live overlays |
| Chaîne U | `tab-chain` | Waterfall + breakdown + time-series for control output |
| Feedforward | `tab-ff` | FF pipeline steps, K_ff calculation, charts |
| Santé modèle | `tab-health` | Model reliability scores and learning progress |
| Événements | `tab-events` | Filtered timeline of state transitions |
| Alertes | `tab-alerts` | 9 configurable threshold rules (LocalStorage) |
| Performance | `tab-perf` | Error metrics, overshoot, deadband analysis |
| Attributs bruts | `tab-raw` | Full JSON attribute dump |

### State & Persistence

- **Global JS state object** holds current entity data, charts, and UI flags
- **Tab routing:** URL hash `#tab-data`, `#tab-history`, etc.
- **Entity selection:** Query param `?entity_id=climate.xyz`
- **Alert thresholds:** Persisted in `localStorage`

---

## Security Conventions

The following security practices are in place — maintain them:

1. **CSP headers** set in `app.py` `@app.after_request`
2. **X-Content-Type-Options: nosniff** and **X-Frame-Options: DENY**
3. **Entity ID regex validation** before passing to HA API — do not bypass
4. **HA token via `.env`** — never hardcode or log
5. **Hours clamped 1–168** for HA history requests (prevents large response attacks)
6. **Auto-generated `FLASK_SECRET_KEY`** if not set

When adding new API endpoints, always validate and sanitize query parameters. Follow the existing pattern in `app.py`.

---

## Key Conventions

### Python

- Use `uv` for all package management (`uv add`, `uv sync`), not pip
- Keep `requirements.txt` in sync with `pyproject.toml` if modified
- Module-level state goes in `config.py`, not scattered across modules
- Async code (WebSocket) runs isolated in its own thread with its own `asyncio` loop
- Log using `logging` (configured in `config.py`) — not `print()`
- Response format: `{"ok": True, ...payload}` or `{"ok": False, "error": "..."}`, HTTP 400 on error

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
3. Return `{"ok": True, ...}` on success, `{"ok": False, "error": "..."}` with HTTP 400 on failure
4. Document the endpoint in the API table in this file

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

---

## What AI Assistants Should Avoid

- **Do not add npm, Node.js, or any JS build toolchain** unless explicitly asked
- **Do not introduce a database** — the in-memory store is intentional for simplicity
- **Do not bypass security validations** (entity ID regex, hours clamping, CSP headers)
- **Do not commit `.env`** — it contains credentials
- **Do not use `print()` for logging** — use the `logging` module
- **Do not modify bundled libraries** (`uPlot.iife.min.js`, `uPlot.min.css`)
- **Do not split `dashboard.html`** into a multi-file frontend without explicit direction — the single-file approach is intentional for easy deployment
