# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""/admin/trigger-deploy — shared-secret gate + delegation to admin.trigger_deploy."""

import admin.trigger_deploy as trigger_deploy


def test_trigger_deploy_requires_secret(client, monkeypatch):
    monkeypatch.setenv("SYNC_SECRET", "testsecret")
    r = client.post("/admin/trigger-deploy")
    assert r.status_code == 403


def test_trigger_deploy_rejects_wrong_secret(client, monkeypatch):
    monkeypatch.setenv("SYNC_SECRET", "testsecret")
    r = client.post("/admin/trigger-deploy", headers={"X-Sync-Secret": "wrong"})
    assert r.status_code == 403


def test_trigger_deploy_calls_trigger_with_correct_secret(client, monkeypatch):
    monkeypatch.setenv("SYNC_SECRET", "testsecret")
    called = {}

    def fake_trigger():
        called["ran"] = True
        return {"ok": True, "ref": "main"}

    monkeypatch.setattr(trigger_deploy, "trigger", fake_trigger)
    r = client.post("/admin/trigger-deploy", headers={"X-Sync-Secret": "testsecret"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "ref": "main"}
    assert called.get("ran")


def test_trigger_requires_pat(monkeypatch):
    monkeypatch.delenv("GITHUB_DEPLOY_PAT", raising=False)
    try:
        trigger_deploy.trigger()
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "GITHUB_DEPLOY_PAT" in str(e)
