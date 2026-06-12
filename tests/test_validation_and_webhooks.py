import pytest

from mojawave_mcp.validation import (
    validate_message,
    validate_phone,
    validate_recipients,
    validate_schedule_at,
    validate_sender_id,
)
from mojawave_mcp.webhooks import compute_signature, verify_signature


def test_validate_phone_ok():
    assert validate_phone(" +255712345678 ") == "+255712345678"


@pytest.mark.parametrize("bad", ["255712345678", "+0712345678", "0712345678", "+abc", "+"])
def test_validate_phone_rejects(bad):
    with pytest.raises(ValueError):
        validate_phone(bad)


def test_validate_sender_id():
    assert validate_sender_id("MojaWave") == "MojaWave"
    with pytest.raises(ValueError):
        validate_sender_id("Too Long Sender")  # >11 and has spaces
    with pytest.raises(ValueError):
        validate_sender_id("has space")


def test_validate_message():
    assert validate_message("hi") == "hi"
    with pytest.raises(ValueError):
        validate_message("")
    with pytest.raises(ValueError):
        validate_message("x" * 1601)


def test_validate_recipients():
    assert validate_recipients(["+255700000001"]) == ["+255700000001"]
    with pytest.raises(ValueError):
        validate_recipients([])
    with pytest.raises(ValueError):
        validate_recipients(["not-a-number"])


def test_validate_schedule_at():
    assert validate_schedule_at("2026-06-15T09:00:00Z") == "2026-06-15T09:00:00Z"
    with pytest.raises(ValueError):
        validate_schedule_at("next tuesday")


def test_webhook_signature_roundtrip():
    body = '{"type":"message.delivered"}'
    secret = "whsec_test"
    sig = compute_signature(body, secret)
    assert verify_signature(body, sig, secret) is True
    assert verify_signature(body, "bad", secret) is False
    assert verify_signature(body, None, secret) is False
    # Raw bytes verify identically.
    assert verify_signature(body.encode(), sig, secret) is True
