import pytest


async def test_health_is_public(anon):
    r = await anon.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["db"] == "ok"


@pytest.mark.parametrize("path", ["/tasks", "/settings", "/summary/today", "/settings/api-key"])
async def test_everything_else_requires_token(anon, path):
    r = await anon.get(path)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_wrong_token_rejected(anon):
    r = await anon.get("/tasks", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
