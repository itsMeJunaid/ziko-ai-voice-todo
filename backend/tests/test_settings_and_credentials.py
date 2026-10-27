"""Settings persistence + API-key write-only semantics (PRD §3.3, §11.1)."""


async def test_defaults_then_patch_persists(client):
    s = (await client.get("/settings")).json()
    assert s["ai"]["model"] == "gemini-3.8-live" and s["voice"]["wake_word_engine"] == "livekit"
    r = await client.patch(
        "/settings", json={"appearance": {"dot_size": 64}, "voice": {"wake_word_enabled": False}}
    )
    assert r.status_code == 200
    s2 = (await client.get("/settings")).json()
    assert s2["appearance"]["dot_size"] == 64 and s2["voice"]["wake_word_enabled"] is False
    assert s2["appearance"]["accent_color"] == "#8b5cf6"  # untouched sibling survives deep merge


async def test_patch_validation(client):
    r = await client.patch("/settings", json={"appearance": {"dot_size": 500}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


async def test_reset(client):
    await client.patch("/settings", json={"appearance": {"dot_size": 64}})
    s = (await client.post("/settings/reset")).json()
    assert s["appearance"]["dot_size"] == 44


async def test_api_key_is_write_only(client, tmp_path):
    assert (await client.get("/settings/api-key")).json() == {
        "has_api_key": False,
        "credential_store": "file",
    }
    r = await client.put("/settings/api-key", json={"api_key": "AIza-test-key-0123456789abcdef"})
    assert r.status_code == 200 and r.json()["has_api_key"] is True
    assert "AIza" not in r.text
    assert (await client.get("/settings")).text.find("AIza") == -1
    assert (await client.get("/settings/api-key")).json()["has_api_key"] is True
    assert (await client.delete("/settings/api-key")).status_code == 200
    assert (await client.get("/settings/api-key")).json()["has_api_key"] is False


async def test_short_key_rejected(client):
    assert (await client.put("/settings/api-key", json={"api_key": "short"})).status_code == 422
