# SmartPI Dashboard

Tableau de bord temps réel pour le régulateur SmartPI (Versatile Thermostat / Home Assistant).

## Architecture

```
smartpi-dashboard/
├── app.py                    # Backend Flask + WebSocket relay vers HA
├── setup_diagram.py          # Extraction SVG du schéma de bloc
├── .env.example              # Template de configuration
├── requirements.txt          # Dépendances Python
├── templates/
│   └── dashboard.html        # Frontend (HTML + Chart.js + JS)
└── static/
    └── block_diagram.svg     # Schéma de bloc interactif (généré)
```

### Backend (Flask)
- Se connecte à Home Assistant via **WebSocket** pour recevoir les changements d'état en temps réel
- Expose une **API REST** pour le frontend :
  - `GET /api/state` — État courant groupé par catégorie SmartPI
  - `GET /api/history` — Historique en mémoire (rolling 500 points)
  - `GET /api/ha-history?hours=24` — Historique depuis l'API REST de HA
  - `GET /api/config` — Configuration des groupes de données
  - `GET /api/block-diagram` — Métadonnées du schéma de bloc

### Frontend
- **Barre héro** : T°, consigne, puissance, T_ext, régime, phase, RMSE twin, ETA
- **Onglet Données** : tous les attributs SmartPI groupés (régulation, modèle, twin, governance, feedforward, calibration, filtre, cycle)
- **Onglet Historique** : graphiques Chart.js temps réel (température, puissance, twin diagnostics)
- **Onglet Schéma Bloc** : SVG interactif du schéma de régulation avec valeurs live
- **Onglet Attributs bruts** : dump JSON complet

## Installation

```bash
# 1. Cloner / copier le projet
cd smartpi-dashboard

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Configurer
cp .env.example .env
# Éditer .env avec votre URL HA, token, et entité climate

# 4. (Optionnel) Extraire le SVG du schéma de bloc
python setup_diagram.py static/smartpi_block_diagram_v2.html

# 5. Lancer
python app.py
```

Le dashboard est accessible sur `http://localhost:5000`.

## Configuration (.env)

| Variable | Description | Exemple |
|---|---|---|
| `HA_URL` | URL du serveur Home Assistant | `http://192.168.1.10:8123` |
| `HA_TOKEN` | Long-Lived Access Token HA | `eyJhbGciOi...` |
| `CLIMATE_ENTITY` | Entité climate Versatile Thermostat | `climate.salon` |
| `FLASK_PORT` | Port du serveur Flask | `5000` |

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
