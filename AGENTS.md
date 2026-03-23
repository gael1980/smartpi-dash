# AGENTS.md — SmartPI Dashboard

Guide projet pour Codex et les autres agents de code intervenant sur `smartpi-dash`.

## Objet du projet

`smartpi-dash` est un tableau de bord temps reel pour le controleur SmartPI de Versatile Thermostat sous Home Assistant.

- Backend: Python 3.10+ avec Flask
- Temps reel: WebSocket Home Assistant via `websockets`
- Frontend: HTML/CSS/JavaScript vanilla dans un seul fichier
- Gestion des dependances: `uv`
- Licence: GPL-3.0-only

## Fichiers cles

- `app.py`: routes Flask, validation des entrees, headers de securite, rate limiting
- `config.py`: chargement `.env`, logging, `state_store`, helpers de stockage partage
- `ha_client.py`: appels REST Home Assistant et cache d'historique
- `ws_listener.py`: listener WebSocket HA dans un thread de fond
- `transforms.py`: mapping SmartPI, groupes, flattening et snapshots d'historique
- `templates/dashboard.html`: UI complete, CSS et JavaScript embarques
- `static/block_diagram.svg`: SVG servi au frontend
- `static/smartpi_block_diagram_v2.html`: source du schema bloc a regenerer si modifie
- `README.md`: installation et configuration

## Commandes utiles

```bash
uv sync
cp .env.example .env
uv run setup_diagram.py
uv run app.py
```

Par defaut, l'application demarre sur `http://127.0.0.1:5000`.

## Invariants a respecter

- Ne jamais committer `.env` ni exposer `HA_TOKEN`.
- Ne pas activer `FLASK_DEBUG`.
- Utiliser `uv` pour installer ou mettre a jour les dependances.
- Garder `requirements.txt` en phase avec `pyproject.toml` si les dependances changent.
- Utiliser `logging`, pas `print()`.
- Le store partage utilise `state_store["connected"]`, pas `ha_connected`.
- Les IDs Home Assistant doivent rester valides cote serveur avant usage.
- Les requetes d'historique Home Assistant doivent conserver leur borne `1..168` heures.
- Les nouveaux endpoints couteux doivent conserver un rate limit explicite.
- Le frontend n'a pas de build step: toute modification UI passe par `templates/dashboard.html`.
- Ne pas introduire React, Vue, npm, Node ou un bundler sans demande explicite.
- Ne pas modifier `static/uPlot.iife.min.js` ni `static/uPlot.min.css` sauf demande explicite.
- Si `static/smartpi_block_diagram_v2.html` change, regenerer `static/block_diagram.svg`.
- Eviter les structures non bornees dans l'historique en memoire.

## Conventions backend

- Le format de reponse attendu reste `{"ok": true, ...}` ou `{"ok": false, "error": "..."}`.
- Utiliser `get_entity_store(entity_id)` depuis `config.py` pour initialiser ou recuperer les slots d'entite.
- Le code async WebSocket doit rester isole dans son propre thread et sa boucle `asyncio`.
- Les nouveaux acces Home Assistant doivent suivre les patterns existants de `ha_client.py` et `ws_listener.py`.

## Conventions frontend

- Garder la structure mono-fichier de `templates/dashboard.html`.
- Reutiliser les variables CSS definies a `:root`; ne pas durcir les couleurs.
- Les nouveaux onglets suivent le pattern bouton + panel + logique `switchTab()`.
- Les graphiques restent sur uPlot.
- L'etat persistant cote navigateur doit passer par `localStorage`.

## Verifications minimales apres changement

- Verifier les imports Python du projet.
- Lancer `uv run app.py` sans erreur de demarrage.
- Verifier `GET /health`.
- Verifier au moins une route API touchee par le changement.
- Si l'UI change, ouvrir le dashboard et valider l'onglet ou le flux modifie.

## Skills du repo

Les skills specifiques au projet vivent dans `.agents/skills/`.

- Ces skills sont maintenant la source de verite pour les workflows specifiques au repo.
- Les skills sont charges a la demande; garder des descriptions precises dans leur frontmatter.
- Les scripts, references et assets associes a une skill doivent rester avec elle.

## Notes de migration

- La cible Codex canonique pour ce repo est `AGENTS.md` plus `.agents/skills/`.
- Les anciens artefacts Claude ont ete retires du repo apres migration.
