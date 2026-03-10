# SmartPI Dashboard

Tableau de bord temps réel pour le régulateur SmartPI (Versatile Thermostat / Home Assistant).

## Architecture

```
smartpi-dash/
├── app.py                    # Routes Flask, rate limiting, sécurité, point d'entrée
├── config.py                 # Variables d'env, logging, state_store, validation
├── transforms.py             # Transformations de données (flatten, extract, snapshot)
├── ha_client.py              # Client REST Home Assistant + découverte d'entités
├── ws_listener.py            # Listener WebSocket HA + thread
├── import.py                 # Utilitaire : migration config Claude Code → ChatGPT project
├── setup_diagram.py          # Extraction SVG du schéma de bloc
├── mcp.json                  # Configuration MCP (CodeGraphContext)
├── .env.example              # Template de configuration
├── .gitignore                # Fichiers exclus du dépôt
├── pyproject.toml            # Dépendances Python (uv)
├── templates/
│   └── dashboard.html        # Frontend (HTML + CSS + uPlot + JS, ~7200 lignes)
└── static/
    ├── block_diagram.svg     # Schéma de bloc interactif (généré)
    ├── smartpi_block_diagram_v2.html  # Source HTML du schéma bloc
    ├── uPlot.iife.min.js     # Librairie de graphiques (bundlée)
    └── uPlot.min.css         # Styles uPlot
```

### Backend (Flask)
- Se connecte à Home Assistant via **WebSocket** pour recevoir les changements d'état en temps réel
- **Auto-découverte** de tous les thermostats SmartPI (multi-entité)
- Expose une **API REST** pour le frontend :
  - `GET /api/entities` — Liste des entités SmartPI découvertes (10 req/min)
  - `GET /api/state?entity_id=...` — État courant groupé ; supporte ETag / `If-None-Match` (60 req/min)
  - `GET /api/history?entity_id=...` — Historique en mémoire (rolling 500 points)
  - `GET /api/ha-history?entity_id=...&hours=24` — Historique HA REST (cache 60s, 10 req/min)
  - `GET /api/config` — Configuration des groupes de données
  - `GET /api/block-diagram` — Métadonnées du schéma de bloc
  - `GET /health` — Health check pour monitoring / load balancer (exempt de rate limit)
- **Rate limiting** par IP via `flask-limiter` (200 req/heure par défaut)

### Frontend
- **Sélecteur d'entité** : choix du thermostat SmartPI à superviser (persisté en localStorage)
- **Barre héro** : T°, consigne, puissance, T_ext, régime, phase, RMSE twin, ETA
- **Onglet Données** : tous les attributs SmartPI groupés (régulation, modèle, twin, governance, feedforward, calibration, filtre, cycle)
- **Onglet Historique** : graphiques uPlot temps réel (température, puissance, twin diagnostics) avec sélecteur de plage (1–48h)
- **Onglet Schéma Bloc** : SVG interactif du schéma de régulation avec valeurs live
- **Onglet Chaîne U** : décomposition de la commande (waterfall `u_applied / u_cmd / u_pi / u_ff_eff`) + détail FFv2 et time-series
- **Onglet FFv2** : état runtime, chaîne `ff_raw -> u_ff_ab -> u_ff_base -> u_ff_eff`, warmup/fiabilité, K_ff, trim/taper, hold estimator, graphiques
- **Onglet Santé Modèle** : score de santé global, drapeaux de fiabilité, autocalib, twin quality, diagnostics FFv2, progression apprentissage, paramètres du modèle
- **Onglet Tuning Assistant** : jauge d'aptitude au tuning (score 0–100%) tenant compte de l'état opératoire, paramètres PI & modèle avec badges fiabilité, contexte d'observabilité (RMSE, innovation, CUSUM avec sparklines de tendance), références théoriques PI (SIMC/IMC), maturité du modèle (apprentissage, autocalib, snapshot), fenêtre de stabilité (durée régime/phase), analyse de la réponse récente (montée, dépassement, stabilisation, verdict), recommandations enrichies en lecture seule
- **Onglet Événements** : timeline chronologique des transitions d'état (régime, phase, FF gate, saturation, deadband, autocalib, guard) avec filtres
- **Onglet Alertes** : règles d'alerte sur RMSE, innovation, deadtimes, tau, modèle dégradé, protections, CUSUM, erreur T°, snapshot age et diagnostics FFv2, avec seuils configurables (persistés en localStorage)
- **Onglet Consigne vs Réalisé** : métriques de performance (erreur moy/max, % deadband/near-band, overshoot, IAE), graphique d'erreur avec bandes colorées, tableau de sessions par changement de consigne
- **Onglet Supervision** : synoptique industriel style SCADA avec indicateurs de flux animés
- **Onglet Attributs bruts** : dump JSON complet

## Installation

> **Prérequis** : [uv](https://docs.astral.sh/uv/) doit être installé.

```bash
# 1. Cloner / copier le projet
cd smartpi-dash

# 2. Installer les dépendances
uv sync

# 3. Configurer
cp .env.example .env
# Éditer .env avec votre URL HA, token, et entité climate

# 4. (Optionnel) Extraire le SVG du schéma de bloc
uv run setup_diagram.py static/smartpi_block_diagram_v2.html

# 5. Lancer
uv run app.py
```

Le dashboard est accessible sur `http://localhost:<FLASK_PORT>` (`5000` par défaut).

## Configuration (.env)

| Variable | Description | Exemple |
|---|---|---|
| `HA_URL` | URL du serveur Home Assistant | `https://192.168.1.10:8123` |
| `HA_TOKEN` | Long-Lived Access Token HA | `eyJhbGciOi...` |
| `CLIMATE_ENTITY` | Entité climate par défaut | `climate.salon` |
| `FLASK_PORT` | Port du serveur Flask | `5000` |
| `FLASK_HOST` | Adresse d'écoute (`127.0.0.1` = local, `0.0.0.0` = réseau) | `127.0.0.1` |
| `FLASK_SECRET_KEY` | Clé secrète Flask (auto-générée si absente) | `a1b2c3d4...` |

> **Accès distant (Pangolin, Cloudflare Tunnel, etc.) :** Par défaut le serveur n'écoute que sur localhost. Pour un accès via un reverse proxy ou tunnel, ajoutez `FLASK_HOST=0.0.0.0` dans votre `.env`.

### Créer un token HA
Profil → Sécurité → Jetons d'accès à longue durée de vie → Créer un jeton

## Données affichées

Le dashboard regroupe automatiquement les attributs SmartPI en catégories :

| Groupe | Contenu |
|---|---|
| ⚡ Régulation PI | Kp, Ki, erreurs, composantes `u_p/u_i/u_pi/u_ff_eff/u_cmd` |
| 🏠 Modèle Thermique | a, b, τ, deadtimes, compteurs d'apprentissage |
| 🔬 Thermal Twin | T̂, innovation, d̂_ema, RMSE, CUSUM, ETA |
| 🛡️ Gouvernance & Sécurité | Régime, phase, action governance, protections, état intégrateur |
| 🎯 Feedforward FFv2 | `K_ff`, `ff_raw`, `u_ff_ab`, `u_ff_base`, `u_ff_eff`, warmup, trim/taper, hold estimator, gate, confidence/coherence |
| 🔧 Calibration & AutoCalib | État FSM, AutoCalib, retry count, snapshot age |
| 📐 Filtre de Consigne | SP_brut, SP_for_P, mode filtre |
| ⏱️ Cycle PWM | Cycle min, état cycle, min_on/min_off |

Les attributs SmartPI non mappés apparaissent automatiquement dans "Autres attributs".

## Licence

Ce projet est distribué sous licence **GNU General Public License v3.0** — voir le fichier [LICENSE](LICENSE) pour plus de détails.
