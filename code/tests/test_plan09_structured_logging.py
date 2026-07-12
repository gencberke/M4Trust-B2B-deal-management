"""Structured-log and provider-exception leakage regression tests."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import requests

from backend.app.services.video import roboflow_client
from backend.app.services.video.exceptions import RoboflowAPIError
from backend.app.structured_logging import AllowlistJSONFormatter


def test_formatter_emits_only_allowlisted_context_and_never_message_payload() -> None:
    secret = "super-secret-reset-token"
    record = logging.LogRecord(
        name="backend.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=(
            "password=%s authorization=Bearer %s user@example.com "
            "4111111111111111 TR000000000000000000000000 C:/sensitive/path"
        ),
        args=(secret, secret),
        exc_info=None,
    )
    record.event = "auth_request_rejected"
    record.request_id = "request-123"
    record.actor_type = "anonymous"
    record.action = "POST_auth_reset"
    record.status_code = 429
    record.unsafe_payload = {"password": secret}

    rendered = AllowlistJSONFormatter().format(record)
    parsed = json.loads(rendered)
    assert parsed["event"] == "auth_request_rejected"
    assert parsed["request_id"] == "request-123"
    assert parsed["status_code"] == 429
    for marker in (
        secret,
        "password",
        "Bearer",
        "user@example.com",
        "4111111111111111",
        "TR000000000000000000000000",
        "sensitive/path",
    ):
        assert marker not in rendered


def test_roboflow_transport_error_does_not_retain_key_in_exception_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "live-provider-key-must-not-leak"
    image = tmp_path / "sensitive-customer-name.jpg"
    image.write_bytes(b"image")

    def fail(*args, **kwargs):
        raise requests.HTTPError(f"403 https://provider.invalid/?api_key={key}")

    monkeypatch.setattr(roboflow_client.requests, "post", fail)
    with pytest.raises(RoboflowAPIError) as caught:
        roboflow_client.infer(image, "model/1", key)
    assert key not in str(caught.value)
    assert caught.value.__cause__ is None
