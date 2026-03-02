"""Home Assistant REST API client and entity discovery."""

import time
from datetime import datetime, timedelta, timezone

import requests

from config import HA_URL, HA_TOKEN, CLIMATE_ENTITY, state_store, log

# ─── REST helpers ────────────────────────────────────────────────


def ha_headers() -> dict:
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }


def ha_get_state(entity_id: str) -> dict | None:
    """Fetch a single entity state via REST."""
    try:
        r = requests.get(
            f"{HA_URL}/api/states/{entity_id}",
            headers=ha_headers(),
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("REST fetch failed for %s: %s", entity_id, e)
        return None


def ha_get_history(entity_id: str, hours: int = 24) -> list:
    """Fetch history for an entity via REST."""
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        r = requests.get(
            f"{HA_URL}/api/history/period/{start.isoformat()}",
            headers=ha_headers(),
            params={
                "filter_entity_id": entity_id,
                "end_time": end.isoformat(),
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        return data[0] if data else []
    except Exception as e:
        log.error("History fetch failed: %s", e)
        return []


# ─── Entity discovery with TTL cache ────────────────────────────

_entities_cache = {"data": [], "ts": 0}
ENTITIES_CACHE_TTL = 60  # seconds


def ha_discover_smartpi_entities() -> list[dict]:
    """Discover all climate entities with SmartPI attributes from HA."""
    now = time.time()
    if _entities_cache["data"] and now - _entities_cache["ts"] < ENTITIES_CACHE_TTL:
        return _entities_cache["data"]

    try:
        r = requests.get(
            f"{HA_URL}/api/states",
            headers=ha_headers(),
            timeout=15,
        )
        r.raise_for_status()
        all_states = r.json()
    except Exception as e:
        log.error("Failed to discover entities: %s", e)
        return _entities_cache["data"]  # return stale cache on error

    entities = []
    for state in all_states:
        eid = state.get("entity_id", "")
        if not eid.startswith("climate."):
            continue
        attrs = state.get("attributes", {})
        specific = attrs.get("specific_states", {})
        if isinstance(specific, dict) and "smart_pi" in specific:
            entities.append({
                "entity_id": eid,
                "friendly_name": attrs.get("friendly_name", eid),
            })

    # Sort: default entity first, then alphabetical
    entities.sort(key=lambda e: (e["entity_id"] != CLIMATE_ENTITY, e["friendly_name"]))

    _entities_cache["data"] = entities
    _entities_cache["ts"] = now
    state_store["known_entities"] = [e["entity_id"] for e in entities]
    log.info("Discovered %d SmartPI entities: %s", len(entities),
             [e["entity_id"] for e in entities])
    return entities
