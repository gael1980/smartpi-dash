# AGENT.md — SmartPI Dashboard

Guide rapide pour tout agent de code intervenant sur `smartpi-dash`.

## Objet du projet

`smartpi-dash` est un tableau de bord temps réel pour le contrôleur SmartPI de Versatile Thermostat sous Home Assistant.

- Backend: Python 3.10+ avec Flask
- Temps réel: WebSocket Home Assistant via `websockets`
- Frontend: HTML/CSS/JavaScript vanilla dans un seul fichier
- Package manager: `uv`
- Licence: GPL-3.0-only

## Fichiers clés

- `app.py` : routes Flask, headers de sécurité, rate limiting, point d'entrée
- `config.py` : chargement `.env`, logging, `state_store`, helpers
- `ha_client.py` : appels REST Home Assistant et cache d'historique
- `ws_listener.py` : listener WebSocket HA dans un thread de fond
- `transforms.py` : mapping SmartPI, groupes, snapshots d'historique
- `templates/dashboard.html` : UI complète, CSS et JavaScript embarqués
- `static/block_diagram.svg` : SVG servi au frontend
- `static/smartpi_block_diagram_v2.html` : source du schéma bloc à régénérer si modifiée

## Commandes utiles

```bash
uv sync
cp .env.example .env
uv run setup_diagram.py static/smartpi_block_diagram_v2.html
uv run app.py
```

Par défaut, l'application démarre sur `http://127.0.0.1:5000`.

## Contraintes de modification

- Ne pas committer `.env` ni exposer `HA_TOKEN`.
- Le frontend n'a pas de build step: toute modification UI passe par `templates/dashboard.html`.
- Ne pas éditer `static/uPlot.iife.min.js` ni `static/uPlot.min.css` sauf demande explicite.
- Si `static/smartpi_block_diagram_v2.html` change, régénérer `static/block_diagram.svg`.
- Le store partagé utilise `state_store["connected"]`, pas `ha_connected`.
- L'historique en mémoire est borné et sert aux endpoints temps réel; éviter les structures non bornées.
- Les IDs d'entité Home Assistant doivent rester validés côté serveur avant usage.

## Vérifications minimales après changement

- Lancer `uv run app.py` sans erreur de démarrage
- Vérifier `/health`
- Vérifier au moins une route API touchée par le changement
- Si UI modifiée, ouvrir le dashboard et valider l'onglet concerné

## Références

- `README.md` : vue d'ensemble, installation, configuration
- `CLAUDE.md` : documentation projet plus détaillée et conventions d'architecture
