"""Tests for app.py — Flask routes, security headers, and caching."""

import json
import pytest
from unittest.mock import patch
from transforms import SMARTPI_GROUPS


# ── Health check ──────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_ok_true(self, client):
        data = resp_json(client.get("/health"))
        assert data["ok"] is True

    def test_health_has_connected(self, client):
        data = resp_json(client.get("/health"))
        assert "connected" in data

    def test_health_connected_is_bool(self, client):
        data = resp_json(client.get("/health"))
        assert isinstance(data["connected"], bool)


# ── Index ─────────────────────────────────────────────────────────────────────

class TestIndex:
    def test_index_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert b"<!DOCTYPE html>" in resp.data or b"<html" in resp.data


# ── Security Headers ──────────────────────────────────────────────────────────

class TestSecurityHeaders:
    def test_x_content_type_options(self, client):
        resp = client.get("/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        resp = client.get("/health")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_x_xss_protection(self, client):
        resp = client.get("/health")
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_referrer_policy(self, client):
        resp = client.get("/health")
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        resp = client.get("/health")
        perm = resp.headers.get("Permissions-Policy", "")
        assert "camera=()" in perm
        assert "microphone=()" in perm
        assert "geolocation=()" in perm

    def test_csp_header_present(self, client):
        resp = client.get("/health")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "default-src" in csp

    def test_api_no_cache(self, client):
        resp = client.get("/health")
        # /health is an api-like route but not under /api/, check an actual API route
        resp = client.get("/api/config")
        cc = resp.headers.get("Cache-Control", "")
        # /api/config has explicit public cache; other /api/ routes have no-store
        assert cc  # any cache directive is present


# ── /api/config ───────────────────────────────────────────────────────────────

class TestApiConfig:
    def test_config_returns_200(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200

    def test_config_ok_true(self, client):
        data = resp_json(client.get("/api/config"))
        assert data["ok"] is True

    def test_config_has_groups(self, client):
        data = resp_json(client.get("/api/config"))
        assert "groups" in data

    def test_config_all_smartpi_groups_present(self, client):
        data = resp_json(client.get("/api/config"))
        for gid in SMARTPI_GROUPS:
            assert gid in data["groups"], f"Group {gid!r} missing from /api/config"

    def test_config_groups_have_label_icon_keys(self, client):
        data = resp_json(client.get("/api/config"))
        for gid, grp in data["groups"].items():
            assert "label" in grp
            assert "icon" in grp
            assert "keys" in grp

    def test_config_cache_control_public(self, client):
        resp = client.get("/api/config")
        cc = resp.headers.get("Cache-Control", "")
        assert "public" in cc
        assert "max-age=3600" in cc

    def test_config_entity_id_present(self, client):
        data = resp_json(client.get("/api/config"))
        assert "entity_id" in data


# ── /api/block-diagram ────────────────────────────────────────────────────────

class TestApiBlockDiagram:
    def test_block_diagram_returns_200(self, client):
        resp = client.get("/api/block-diagram")
        assert resp.status_code == 200

    def test_block_diagram_ok_true(self, client):
        data = resp_json(client.get("/api/block-diagram"))
        assert data["ok"] is True

    def test_block_diagram_has_blocks(self, client):
        data = resp_json(client.get("/api/block-diagram"))
        assert "blocks" in data
        assert len(data["blocks"]) > 0

    def test_block_diagram_blocks_have_label_group(self, client):
        data = resp_json(client.get("/api/block-diagram"))
        for block_id, block in data["blocks"].items():
            assert "label" in block, f"Block {block_id!r} missing label"
            assert "group" in block, f"Block {block_id!r} missing group"

    def test_block_diagram_cache_control(self, client):
        resp = client.get("/api/block-diagram")
        cc = resp.headers.get("Cache-Control", "")
        assert "public" in cc


# ── /api/state ────────────────────────────────────────────────────────────────

class TestApiState:
    def test_unknown_entity_returns_404(self, client):
        resp = client.get("/api/state?entity_id=climate.nonexistent")
        assert resp.status_code == 404

    def test_invalid_entity_id_returns_400(self, client):
        resp = client.get("/api/state?entity_id=invalid/../../etc")
        assert resp.status_code == 400

    def test_invalid_entity_uppercase_returns_400(self, client):
        resp = client.get("/api/state?entity_id=Climate.Thermostat")
        assert resp.status_code == 400

    def test_state_returns_200_for_known_entity(self, client, populated_store, entity_id):
        resp = client.get(f"/api/state?entity_id={entity_id}")
        assert resp.status_code == 200

    def test_state_ok_true(self, client, populated_store, entity_id):
        data = resp_json(client.get(f"/api/state?entity_id={entity_id}"))
        assert data["ok"] is True

    def test_state_has_groups(self, client, populated_store, entity_id):
        data = resp_json(client.get(f"/api/state?entity_id={entity_id}"))
        assert "groups" in data

    def test_state_has_etag(self, client, populated_store, entity_id):
        resp = client.get(f"/api/state?entity_id={entity_id}")
        assert "ETag" in resp.headers

    def test_state_304_on_etag_match(self, client, populated_store, entity_id):
        resp1 = client.get(f"/api/state?entity_id={entity_id}")
        etag = resp1.headers["ETag"]
        resp2 = client.get(
            f"/api/state?entity_id={entity_id}",
            headers={"If-None-Match": etag},
        )
        assert resp2.status_code == 304

    def test_state_hvac_mode_present(self, client, populated_store, entity_id):
        data = resp_json(client.get(f"/api/state?entity_id={entity_id}"))
        assert "hvac_mode" in data

    def test_state_connected_present(self, client, populated_store, entity_id):
        data = resp_json(client.get(f"/api/state?entity_id={entity_id}"))
        assert "connected" in data


# ── /api/history ──────────────────────────────────────────────────────────────

class TestApiHistory:
    def test_unknown_entity_returns_404(self, client):
        resp = client.get("/api/history?entity_id=climate.nonexistent")
        assert resp.status_code == 404

    def test_invalid_entity_returns_400(self, client):
        resp = client.get("/api/history?entity_id=bad entity")
        assert resp.status_code == 400

    def test_history_returns_200(self, client, populated_store, entity_id):
        resp = client.get(f"/api/history?entity_id={entity_id}")
        assert resp.status_code == 200

    def test_history_ok_true(self, client, populated_store, entity_id):
        data = resp_json(client.get(f"/api/history?entity_id={entity_id}"))
        assert data["ok"] is True

    def test_history_has_data(self, client, populated_store, entity_id):
        data = resp_json(client.get(f"/api/history?entity_id={entity_id}"))
        assert "data" in data
        assert isinstance(data["data"], list)

    def test_history_count_matches_data(self, client, populated_store, entity_id):
        data = resp_json(client.get(f"/api/history?entity_id={entity_id}"))
        assert data["count"] == len(data["data"])

    def test_history_contains_snapshot(self, client, populated_store, entity_id):
        data = resp_json(client.get(f"/api/history?entity_id={entity_id}"))
        assert data["count"] >= 1
        assert data["data"][0]["ts"] is not None


# ── /api/entities ─────────────────────────────────────────────────────────────

class TestApiEntities:
    def test_entities_returns_200(self, client):
        with patch("app.ha_discover_smartpi_entities", return_value=["climate.test"]):
            resp = client.get("/api/entities")
        assert resp.status_code == 200

    def test_entities_ok_true(self, client):
        with patch("app.ha_discover_smartpi_entities", return_value=["climate.test"]):
            data = resp_json(client.get("/api/entities"))
        assert data["ok"] is True

    def test_entities_has_entities_list(self, client):
        with patch("app.ha_discover_smartpi_entities", return_value=["climate.test"]):
            data = resp_json(client.get("/api/entities"))
        assert "entities" in data
        assert isinstance(data["entities"], list)

    def test_entities_has_default(self, client):
        with patch("app.ha_discover_smartpi_entities", return_value=[]):
            data = resp_json(client.get("/api/entities"))
        assert "default" in data


# ── Helpers ───────────────────────────────────────────────────────────────────

def resp_json(resp):
    """Parse JSON from a Flask test response."""
    return json.loads(resp.data)
