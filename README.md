# SmartPI Dashboard

Tableau de bord temps réel pour le régulateur SmartPI (Versatile Thermostat / Home Assistant).

## Architecture

```
smartpi-dash/
├── app.py                    # Routes Flask, sécurité, point d'entrée
├── config.py                 # Variables d'env, logging, state_store, validation
├── transforms.py             # Transformations de données (flatten, extract, snapshot)
├── ha_client.py              # Client REST Home Assistant + découverte d'entités
├── ws_listener.py            # Listener WebSocket HA + thread
├── setup_diagram.py          # Extraction SVG du schéma de bloc
├── .env.example              # Template de configuration
├── .gitignore                # Fichiers exclus du dépôt
├── pyproject.toml            # Dépendances Python (uv)
├── templates/
│   └── dashboard.html        # Frontend (HTML + CSS + uPlot + JS)
└── static/
    ├── block_diagram.svg     # Schéma de bloc interactif (généré)
    ├── uPlot.iife.min.js     # Librairie de graphiques (bundlée)
    └── uPlot.min.css         # Styles uPlot
```

### Backend (Flask)
- Se connecte à Home Assistant via **WebSocket** pour recevoir les changements d'état en temps réel
- **Auto-découverte** de tous les thermostats SmartPI (multi-entité)
- Expose une **API REST** pour le frontend :
  - `GET /api/entities` — Liste des entités SmartPI découvertes
  - `GET /api/state?entity_id=...` — État courant groupé par catégorie SmartPI
  - `GET /api/history?entity_id=...` — Historique en mémoire (rolling 500 points)
  - `GET /api/ha-history?entity_id=...&hours=24` — Historique depuis l'API REST de HA
  - `GET /api/config` — Configuration des groupes de données
  - `GET /api/block-diagram` — Métadonnées du schéma de bloc

### Frontend
- **Sélecteur d'entité** : choix du thermostat SmartPI à superviser (persisté en localStorage)
- **Barre héro** : T°, consigne, puissance, T_ext, régime, phase, RMSE twin, ETA
- **Onglet Données** : tous les attributs SmartPI groupés (régulation, modèle, twin, governance, feedforward, calibration, filtre, cycle)
- **Onglet Historique** : graphiques uPlot temps réel (température, puissance, twin diagnostics) avec sélecteur de plage (1–48h)
- **Onglet Schéma Bloc** : SVG interactif du schéma de régulation avec valeurs live
- **Onglet Chaîne U** : décomposition de la commande (waterfall u_applied / u_ff / u_pi) + time-series
- **Onglet Feedforward** : état FF, pipeline de calcul, warmup, K_ff, graphiques
- **Onglet Santé Modèle** : score de santé global, drapeaux de fiabilité, autocalib, twin quality, progression apprentissage, paramètres du modèle
- **Onglet Événements** : timeline chronologique des transitions d'état (régime, phase, FF gate, saturation, deadband, autocalib, guard) avec filtres
- **Onglet Alertes** : 9 règles d'alerte (RMSE, innovation, deadtime, tau, modèle dégradé, guard cut, CUSUM, erreur T°, snapshot age) avec seuils configurables (persistés en localStorage)
- **Onglet Consigne vs Réalisé** : métriques de performance (erreur moy/max, % deadband/near-band, overshoot, IAE), graphique d'erreur avec bandes colorées, tableau de sessions par changement de consigne
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

Le dashboard est accessible sur `http://localhost:5000`.

## Configuration (.env)

| Variable | Description | Exemple |
|---|---|---|
| `HA_URL` | URL du serveur Home Assistant | `http://192.168.1.10:8123` |
| `HA_TOKEN` | Long-Lived Access Token HA | `eyJhbGciOi...` |
| `CLIMATE_ENTITY` | Entité climate par défaut | `climate.salon` |
| `FLASK_PORT` | Port du serveur Flask | `5000` |
| `FLASK_SECRET_KEY` | Clé secrète Flask (auto-générée si absente) | `a1b2c3d4...` |

### Créer un token HA
Profil → Sécurité → Jetons d'accès à longue durée de vie → Créer un jeton

## Données affichées

Le dashboard regroupe automatiquement les attributs SmartPI en catégories :

| Groupe | Contenu |
|---|---|
| ⚡ Régulation PI | Kp, Ki, erreurs, composantes u_p/u_i/u_ff |
| 🏠 Modèle Thermique | a, b, τ, deadtimes, compteurs d'apprentissage |
| 🔬 Thermal Twin | T̂, innovation, d̂_ema, RMSE, CUSUM, ETA |
| 🛡️ Gouvernance | Régime, phase, action governance, état intégrateur |
| 🎯 Feedforward | K_ff, u_ff, warmup, gate |
| 🔧 Calibration | État FSM, AutoCalib, retry count |
| 📐 Filtre Consigne | SP_brut, SP_for_P, mode filtre |
| ⏱️ Cycle PWM | Cycle min, état cycle, min_on/min_off |

Les attributs SmartPI non mappés apparaissent automatiquement dans "Autres attributs".
