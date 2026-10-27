import logging

from app.core.logging import RedactSecrets


def _render(msg: str, *args) -> str:
    rec = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, msg, args, None)
    RedactSecrets().filter(rec)
    return rec.getMessage()


def test_ws_query_token_is_masked():
    # the exact shape uvicorn logs on WebSocket accept
    out = _render(
        '%s - "WebSocket %s" [accepted]', "127.0.0.1:47960", "/ws/events?token=498749b0955263c5&x=1"
    )
    assert "498749b0955263c5" not in out
    assert "token=***&x=1" in out


def test_bearer_header_is_masked_and_plain_text_untouched():
    assert _render("Authorization: Bearer abc.def-123") == "Authorization: Bearer ***"
    assert _render("GET /tasks 200") == "GET /tasks 200"
