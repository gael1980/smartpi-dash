"""WebSocket listener for Home Assistant state changes (runs in background thread)."""

import json
import asyncio
import threading

import websockets

from config import WS_URL, HA_TOKEN, CLIMATE_ENTITY, state_store, MAX_HISTORY, get_entity_store, log
from transforms import flatten_smartpi_attrs, snapshot_for_history, ensure_utc_iso
from ha_client import ha_discover_smartpi_entities, ha_get_state


async def _ws_listener():
    """Connect to HA WebSocket and subscribe to state changes."""
    msg_id = 1

    while True:
        try:
            log.info("Connecting to HA WebSocket: %s", WS_URL)
            async with websockets.connect(
                WS_URL,
                ping_interval=30,
                ping_timeout=10,
            ) as ws:
                # Phase 1: auth_required
                msg = json.loads(await ws.recv())
                if msg.get("type") != "auth_required":
                    log.warning("Unexpected first message: %s", msg.get("type"))

                # Phase 2: authenticate
                await ws.send(json.dumps({
                    "type": "auth",
                    "access_token": HA_TOKEN,
                }))
                msg = json.loads(await ws.recv())
                if msg.get("type") != "auth_ok":
                    log.error("Auth failed: %s", msg)
                    await asyncio.sleep(10)
                    continue

                log.info("WebSocket authenticated ✓")
                state_store["connected"] = True

                # Phase 3: Subscribe to state_changed events
                subscribe_id = msg_id
                msg_id += 1
                await ws.send(json.dumps({
                    "id": subscribe_id,
                    "type": "subscribe_events",
                    "event_type": "state_changed",
                }))

                # Discover SmartPI entities and do initial REST fetch
                discovered = ha_discover_smartpi_entities()
                known_ids = set(e["entity_id"] for e in discovered)

                # Ensure the default entity is always tracked even if discovery fails
                if CLIMATE_ENTITY not in known_ids:
                    known_ids.add(CLIMATE_ENTITY)

                for eid in known_ids:
                    initial = ha_get_state(eid)
                    if initial:
                        estore = get_entity_store(eid)
                        raw_attrs = initial.get("attributes", {})
                        attrs = flatten_smartpi_attrs(raw_attrs)
                        estore["climate"] = initial
                        estore["attributes"] = attrs
                        estore["last_update"] = ensure_utc_iso(initial.get("last_updated"))
                        log.info("Initial state loaded for %s", eid)

                # Phase 4: Listen for events
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") != "event":
                        continue

                    event = msg.get("event", {})
                    data = event.get("data", {})
                    entity_id = data.get("entity_id", "")

                    # Track all known SmartPI climate entities
                    if entity_id in known_ids:
                        new_state = data.get("new_state", {})
                        raw_attrs = new_state.get("attributes", {})
                        attrs = flatten_smartpi_attrs(raw_attrs)
                        estore = get_entity_store(entity_id)
                        estore["climate"] = new_state
                        estore["attributes"] = attrs
                        estore["last_update"] = ensure_utc_iso(new_state.get("last_updated"))

                        # Append to rolling history (deque auto-evicts oldest)
                        snap = snapshot_for_history(attrs)
                        estore["history"].append(snap)

                        log.debug("[%s] State updated: T=%.1f, on_pct=%s",
                                  entity_id,
                                  attrs.get("current_temperature", 0),
                                  attrs.get("on_percent", "?"))

                    # Also capture related sensor entities for any known climate entity
                    elif any(entity_id.startswith(eid.replace("climate.", "sensor."))
                             for eid in known_ids):
                        # Find which climate entity this sensor belongs to
                        for eid in known_ids:
                            prefix = eid.replace("climate.", "sensor.")
                            if entity_id.startswith(prefix):
                                new_state = data.get("new_state", {})
                                estore = get_entity_store(eid)
                                estore["sensors"][entity_id] = {
                                    "state": new_state.get("state"),
                                    "attributes": new_state.get("attributes", {}),
                                    "last_changed": new_state.get("last_changed"),
                                }
                                break

        except websockets.exceptions.ConnectionClosed:
            log.warning("WebSocket connection closed, reconnecting in 5s...")
            state_store["connected"] = False
            await asyncio.sleep(5)
        except Exception as e:
            log.error("WebSocket error: %s, reconnecting in 10s...", e)
            state_store["connected"] = False
            await asyncio.sleep(10)


def start_ws_thread():
    """Start the WebSocket listener in a daemon thread."""
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_ws_listener())

    t = threading.Thread(target=run, daemon=True, name="ws-listener")
    t.start()
    log.info("WebSocket listener thread started")
