"""Voice state machine with a fake Gemini Live connector and fake audio (PRD §4.3, §4.4, §11.2, §14 Voice)."""

from __future__ import annotations

import asyncio

import httpx

from app.services.gemini_live_service import (
    AudioOut,
    Interrupted,
    LiveError,
    ToolCalls,
    Transcript,
    TurnComplete,
)

from .fakes import LOUD, QUIET, Events, settle


async def test_without_a_key_voice_explains_and_manual_mode_still_works(api, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    s = (await api.post("/voice/start")).json()
    assert (
        s["state"] == "error" and s["error"]["code"] == "no_api_key" and "Settings" in s["error"]["message"]
    )
    assert (await api.post("/tasks", json={"title": "Still works"})).status_code == 201


async def test_start_listens_and_streams_mic_audio(api, connector, audio):
    s = (await api.post("/voice/start")).json()
    assert s["state"] == "listening" and s["mic_active"] is True and s["model"] == "fake-live"
    call = connector.calls[0]
    assert len(call["tools"]) == 11 and "get_current_datetime" in call["system"]
    assert call["models"] == ["gemini-3.8-live", "gemini-2.5-flash-native-audio-preview-12-2025"]
    audio.on_frame(QUIET)
    await settle()
    assert connector.sessions[0].audio == [QUIET]


async def test_tool_call_saves_the_task_before_the_model_hears_about_it(api, connector, audio):
    with Events() as ev:
        await api.post("/voice/start")
        s = connector.sessions[0]
        s.inbox.put_nowait(Transcript("user", "add buy milk tomorrow at 10"))
        s.inbox.put_nowait(
            ToolCalls([("c1", "create_task", {"title": "Buy milk", "due_at": "2026-10-27T10:00"})])
        )
        await settle()
        assert [x["state"] for x in ev.drain("voice.state")][-1] == "processing"
        call_id, name, result = s.tool_results[0]
        assert (call_id, name, result["ok"]) == ("c1", "create_task", True)
        saved = (await api.get(f"/tasks/{result['task']['id']}")).json()
        assert saved["title"] == "Buy milk" and saved["source"] == "voice"

        s.inbox.put_nowait(AudioOut(b"\x01\x00" * 100))
        s.inbox.put_nowait(Transcript("assistant", "Added buy milk for tomorrow at 10."))
        await settle()
        assert bytes(audio.played) == b"\x01\x00" * 100
        s.inbox.put_nowait(TurnComplete())
        await settle()
        states = [x["state"] for x in ev.drain("voice.state")]
        assert states[0] == "speaking" and states[-1] == "listening"


async def test_a_turn_with_only_tool_calls_keeps_processing(api, connector):
    """Real Gemini: tool_call → turn_complete, then the answer arrives in a new turn."""
    await api.post("/voice/text", json={"text": "add tea"})
    s = connector.sessions[0]
    s.inbox.put_nowait(ToolCalls([("c1", "get_current_datetime", {})]))
    s.inbox.put_nowait(TurnComplete())
    await settle()
    assert (await api.get("/voice")).json()["state"] == "processing"
    s.inbox.put_nowait(Transcript("assistant", "Done."))
    s.inbox.put_nowait(TurnComplete())
    await settle()
    assert (await api.get("/voice")).json()["state"] == "idle"


async def test_a_request_gemini_never_answers_times_out(api, app, connector):
    t = [1000.0]
    app.state.voice.monotonic = lambda: t[0]
    await api.post("/voice/text", json={"text": "add tea"})
    t[0] += 21
    await asyncio.sleep(1.2)
    await settle()
    st = (await api.get("/voice")).json()
    assert st["state"] == "error" and st["error"]["code"] == "no_reply" and connector.sessions[0].closed


async def test_tool_errors_reach_the_model_as_data(api, connector):
    await api.post("/voice/start")
    s = connector.sessions[0]
    s.inbox.put_nowait(ToolCalls([("c1", "complete_task", {"task": "nonexistent"}), ("c2", "rm_rf", {})]))
    await settle()
    assert [r[2]["error"]["code"] for r in s.tool_results] == ["not_found", "unknown_tool"]
    assert (await api.get("/voice")).json()["state"] == "processing"  # still in the conversation


async def test_text_turn_goes_through_the_same_session(api, connector):
    with Events() as ev:
        s = (await api.post("/voice/text", json={"text": "what's on today?"})).json()
        assert s["state"] == "processing" and s["mic_active"] is False
        assert connector.sessions[0].texts == ["what's on today?"]
        assert ev.drain("voice.transcript")[0] == {"role": "user", "text": "what's on today?", "final": True}
        connector.sessions[0].inbox.put_nowait(TurnComplete())
        await settle()
        assert (await api.get("/voice")).json()["state"] == "idle"  # no mic: back to idle, session kept


async def test_own_voice_is_ignored_but_a_loud_user_barges_in(api, connector, audio):
    await api.post("/voice/start")
    s = connector.sessions[0]
    audio.playing_flag = True
    audio.on_frame(QUIET)  # speaker echo level
    await settle()
    assert s.audio == [] and audio.cleared == 0
    with Events() as ev:
        audio.on_frame(LOUD)
        await settle()
        assert s.audio == [LOUD] and audio.cleared == 1
        assert [x["state"] for x in ev.drain("voice.state")] == ["interrupted", "listening"]


async def test_server_interruption_stops_playback(api, connector, audio):
    await api.post("/voice/start")
    connector.sessions[0].inbox.put_nowait(Interrupted())
    await settle()
    assert audio.cleared == 1 and (await api.get("/voice")).json()["state"] == "listening"


async def test_offline_retries_three_times_then_errors(api, connector):
    connector.failures = [OSError("network down")] * 3
    s = (await api.post("/voice/start")).json()
    assert len(connector.calls) == 3 and s["state"] == "error" and s["error"]["code"] == "offline"


async def test_a_transient_network_error_reconnects(api, connector):
    connector.failures = [OSError("blip")]
    s = (await api.post("/voice/start")).json()
    assert len(connector.calls) == 2 and s["state"] == "listening"


async def test_bad_key_is_not_retried(api, connector):
    connector.failures = [LiveError("invalid_key", "Gemini rejected the API key. Check it in Settings.")]
    s = (await api.post("/voice/start")).json()
    assert len(connector.calls) == 1 and s["error"]["code"] == "invalid_key"


async def test_a_dropped_session_errors_without_losing_tasks(api, connector, audio):
    await api.post("/voice/start")
    s = connector.sessions[0]
    s.inbox.put_nowait(ToolCalls([("c1", "create_task", {"title": "Keep me"})]))
    await settle()
    s.inbox.put_nowait(ConnectionError("connection reset"))
    await settle()
    st = (await api.get("/voice")).json()
    assert st["state"] == "error" and st["error"]["code"] == "offline" and st["mic_active"] is False
    assert s.closed and audio.closed
    assert (await api.get("/tasks?view=pending")).json()["items"][0]["title"] == "Keep me"


async def test_mute_ends_the_session_and_blocks_start(api, connector, audio):
    await api.post("/voice/start")
    s = (await api.post("/voice/mute", json={"muted": True})).json()
    assert s["state"] == "muted" and s["mic_active"] is False and connector.sessions[0].closed
    assert audio.on_frame is None
    r = await api.post("/voice/start")
    assert r.status_code == 409 and r.json()["error"]["message"] == "The microphone is muted."
    assert (await api.post("/voice/mute", json={"muted": False})).json()["state"] == "idle"


async def test_stop_and_idle_timeout_close_the_session(api, app, connector):
    await api.post("/voice/start")
    assert (await api.post("/voice/stop")).json() == {
        "state": "idle", "silence_timeout_s": 10, "muted": False, "mic_active": False, "error": None,
        "model": None,
    }  # fmt: skip
    assert connector.sessions[0].closed
    t = [1000.0]
    app.state.voice.monotonic = lambda: t[0]
    await api.post("/voice/start")
    t[0] += 11  # default interaction_timeout_s is 10
    await asyncio.sleep(1.2)  # one watchdog tick
    await settle()
    assert connector.sessions[1].closed and (await api.get("/voice")).json()["state"] == "idle"


async def test_mic_closes_after_10s_of_silence_but_not_while_the_user_talks(api, app, connector, audio):
    t = [1000.0]
    app.state.voice.monotonic = lambda: t[0]
    await api.post("/voice/start")
    t[0] += 8
    audio.on_frame(LOUD)  # still talking at 8 s: the 10 s silence timer restarts
    t[0] += 8
    await asyncio.sleep(1.2)
    assert (await api.get("/voice")).json()["mic_active"] is True  # 16 s in, only 8 s quiet
    audio.on_frame(QUIET)  # room noise is silence
    t[0] += 3
    await asyncio.sleep(1.2)
    await settle()
    st = (await api.get("/voice")).json()
    assert st["mic_active"] is False and st["state"] == "idle" and connector.sessions[0].closed
    assert audio.on_frame is None  # the microphone itself is released


async def test_voice_replies_can_be_turned_off(api, connector, audio):
    await api.patch("/settings", json={"voice": {"voice_replies_enabled": False}})
    await api.post("/voice/start")
    connector.sessions[0].inbox.put_nowait(AudioOut(b"\x01\x00" * 10))
    await settle()
    assert audio.played == bytearray()


async def test_voice_endpoints_need_the_token(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as anon:
        assert (await anon.post("/voice/start")).status_code == 401


async def test_hey_ziko_greets_with_todays_plan_then_listens(api, app, connector):
    from app.services.voice_service import GREETING_CUE

    with Events() as ev:
        st = await app.state.voice.start(greet=True)  # what the wake word does
        assert st["state"] == "processing" and st["mic_active"] is True
        s = connector.sessions[0]
        assert s.texts == [GREETING_CUE] and "get_daily_summary" in GREETING_CUE
        assert ev.drain("voice.transcript") == []  # the cue is never shown as something the user said
        s.inbox.put_nowait(ToolCalls([("c1", "get_daily_summary", {})]))
        s.inbox.put_nowait(TurnComplete())
        s.inbox.put_nowait(Transcript("assistant", "Hi Boss! How's it going? Your day is clear."))
        s.inbox.put_nowait(TurnComplete())
        await settle()
        assert s.tool_results[0][2]["ok"] is True
        assert (await api.get("/voice")).json()["state"] == "listening"  # then it waits for the request


async def test_mic_button_does_not_greet_and_greeting_can_be_turned_off(api, app, connector):
    await api.post("/voice/start")  # mic button / double-click: straight to listening
    assert connector.sessions[0].texts == []
    await api.post("/voice/stop")
    await api.patch("/settings", json={"voice": {"greet_on_wake": False}})
    st = await app.state.voice.start(greet=True)
    assert st["state"] == "listening" and connector.sessions[1].texts == []


async def test_ziko_uses_the_name_you_choose(api, connector):
    await api.patch("/settings", json={"voice": {"call_me": "Captain"}})
    await api.post("/voice/start")
    system = connector.calls[0]["system"]
    assert "Captain" in system and "Boss" not in system
    assert "joke" in system and "Never claim you created" in system  # personality, but the rules stay
