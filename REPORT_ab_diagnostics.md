# REPORT — Pentes apprentissage (24h)

## Fichiers modifiés
- `templates/dashboard.html`
- `transforms.py`

## Section ajoutée
- Nouveau bloc dans **Santé Modèle**: **"Pentes apprentissage (24h) — segments uniquement"**.
- 3 graphiques:
  1. `dT/dt recomputed (ON/OFF)`
  2. `A — attribut vs recalculé (ON windows)`
  3. `B — attribut vs recalculé (OFF windows)`
- Le bloc **🩻 Diagnostic 3h (T_int + pentes d'apprentissage)** est inchangé.

## Source de données (24h)
Historique SmartPI existant uniquement (pas de nouvelles entités HA):
- `sensor_temperature` / `current_temperature` -> `t_in`
- `smartpi_t_ext` -> `t_ext`
- `u_applied`
- `a`, `b`
- `learn_ok_count_a`, `learn_ok_count_b`
- `learn_skip_count` (contexte)
- `learn_last_reason` (tooltips rejet)

## Reconstruction des fenêtres (segments)
Règles de régime:
- ON: `u_applied >= U_ON_MIN`
- OFF: `u_applied <= U_OFF_MAX`
- sinon: segment ignoré (`mid-range`)

Constantes SmartPI appliquées:
- `U_ON_MIN = 0.20`
- `U_OFF_MAX = 0.05`
- `DELTA_MIN_ON = 0.2`
- `DELTA_MIN_OFF = 0.5`
- `DT_DERIVATIVE_MIN_ABS = 0.03`

Durée minimale segment candidat:
- ON: `EPISODE_MIN_DURATION_ON_S = 600s`
- OFF: `EPISODE_MIN_DURATION_OFF_S = 900s`

Note: `learning_window.py` local n’expose pas explicitement ces deux constantes; le dashboard applique les valeurs documentées du cœur SmartPI.

## Recalcul de pente par fenêtre
Pour chaque segment candidat, le dashboard applique la logique de `robust_dTdt_per_min`:
- minimum d’échantillons
- garde amplitude (`low_amplitude`)
- régression linéaire (least squares)
- garde pente minimale (`low_slope`)
- clamp final à `[-0.35, +0.35]` °C/min

Conformité `learning_window.py`:
- OFF: `trim_start_frac = 0.10`
- ON: `trim_start_frac = 0.0`

Sorties sparse:
- `dTdt_on[t]` rempli uniquement pendant segments ON candidats
- `dTdt_off[t]` rempli uniquement pendant segments OFF candidats
- hors segments candidats: `null`

Fenêtres rejetées:
- marquées sur le chart 1 avec raison (`insufficient_samples`, `low_amplitude`, `low_slope`, etc.), durée, et contexte `learn_last_reason`.

## Formules A/B recalculées
### A (fenêtres ON valides)
- `delta = mean(T_int - T_ext)` sur la fenêtre
- `u = mean(u_applied)` sur la fenêtre
- `b_attr = b` au milieu de fenêtre
- `a_meas = (dTdt + b_attr * delta) / u`

Guards appliqués (learning.py):
- `u > U_ON_MIN`
- `|delta| >= DELTA_MIN_ON`
- `|dTdt| <= 0.35`
- soft-gate A: `learn_ok_count_b >= 5`
- `a_meas > 0`

Sinon: `a_meas_recomputed = null` + marqueur rejet avec raison.

### B (fenêtres OFF valides)
- `delta = mean(T_int - T_ext)` sur la fenêtre
- `b_meas = -dTdt / delta`

Guards appliqués (learning.py):
- `u < U_OFF_MAX`
- `|delta| >= DELTA_MIN_OFF`
- `|dTdt| <= 0.35`
- `b_meas > 0`

Sinon: `b_meas_recomputed = null` + marqueur rejet avec raison.

## Marqueurs d’acceptation (counter delta)
Ajout sur charts A/B:
- si `learn_ok_count_a[i] - learn_ok_count_a[i-1] > 0` -> marqueur accept A
- si `learn_ok_count_b[i] - learn_ok_count_b[i-1] > 0` -> marqueur accept B
- reset compteur (delta négatif) ignoré (`max(0, delta)`)

## Données manquantes / invalides
- Données non numériques -> ignorées.
- `t_ext` manquant -> pas de `a_meas`/`b_meas` sur la fenêtre.
- `u_applied` normalisé en [0..1] (conversion auto si source en %).
- Si historique mémoire < 24h, fallback HA history est forcé à 24h min.

## Limitation cadence dashboard
- La durée d’un segment est évaluée de façon conservatrice par `t_fin - t_début` (sans interpolation intra-cycle).
- Avec une cadence irrégulière, la qualification de certaines fenêtres proches du seuil peut être plus stricte que le cycle natif SmartPI.
