import httpx
import pytest
import respx

from mojawave_mcp.client import MojaWaveClient, MojaWaveError

BASE = "https://api.mojawave.com/v1"


@pytest.fixture
async def client():
    c = MojaWaveClient(api_key="sk_test_x", max_retries=2)
    yield c
    await c.aclose()


@respx.mock
async def test_send_sms_unwraps_envelope_and_maps_from(client):
    route = respx.post(f"{BASE}/sms/send").mock(
        return_value=httpx.Response(201, json={"success": True, "data": {"id": "abc", "status": "sent"}})
    )
    result = await client.send_sms(to="+255712345678", message="hi", sender_id="MYAPP")
    assert result == {"id": "abc", "status": "sent"}  # envelope unwrapped

    body = route.calls[0].request
    import json

    sent = json.loads(body.content)
    assert sent["from"] == "MYAPP"
    assert "schedule_at" not in sent  # None values stripped
    assert body.headers["authorization"] == "Bearer sk_test_x"
    assert body.headers["x-api-key"] == "sk_test_x"


@respx.mock
async def test_bulk_maps_recipients(client):
    route = respx.post(f"{BASE}/sms/bulk").mock(
        return_value=httpx.Response(202, json={"data": {"job_id": "j1", "status": "scheduled"}})
    )
    await client.send_bulk_sms(recipients=["+255700000001", "+255700000002"], message="hi", sender_id="MYAPP")
    import json

    sent = json.loads(route.calls[0].request.content)
    assert sent["recipients"] == [{"to": "+255700000001"}, {"to": "+255700000002"}]


@respx.mock
async def test_credit_balance(client):
    respx.get(f"{BASE}/credits").mock(
        return_value=httpx.Response(200, json={"data": {"sms": {"balance": 10}}})
    )
    bal = await client.get_credit_balance()
    assert bal["sms"]["balance"] == 10


@respx.mock
async def test_error_mapping_402(client):
    respx.post(f"{BASE}/sms/send").mock(
        return_value=httpx.Response(402, json={"code": "insufficient_balance", "message": "low"})
    )
    with pytest.raises(MojaWaveError) as exc:
        await client.send_sms(to="+255712345678", message="hi", sender_id="MYAPP")
    assert exc.value.status_code == 402
    assert exc.value.code == "insufficient_balance"


@respx.mock
async def test_error_code_falls_back_to_status(client):
    # Body without a `code` field -> derived from HTTP status.
    respx.get(f"{BASE}/credits").mock(return_value=httpx.Response(401, json={"message": "bad key"}))
    with pytest.raises(MojaWaveError) as exc:
        await client.get_credit_balance()
    assert exc.value.code == "unauthorized"


@respx.mock
async def test_retries_429_then_succeeds(client):
    route = respx.get(f"{BASE}/credits").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}, json={"code": "rate_limit_exceeded", "message": "slow"}),
            httpx.Response(200, json={"data": {"sms": {"balance": 5}}}),
        ]
    )
    bal = await client.get_credit_balance()
    assert bal["sms"]["balance"] == 5
    assert route.call_count == 2


@respx.mock
async def test_retries_exhausted_raises(client):
    respx.get(f"{BASE}/credits").mock(
        return_value=httpx.Response(503, headers={"Retry-After": "0"}, json={"message": "down"})
    )
    with pytest.raises(MojaWaveError) as exc:
        await client.get_credit_balance()
    assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


@respx.mock
async def test_list_sms_sender_ids(client):
    respx.get(f"{BASE}/sms/sender-ids/approved").mock(
        return_value=httpx.Response(200, json={"data": {"items": [{"sender_id": "MYAPP", "status": "approved"}], "total": 1}})
    )
    result = await client.list_sms_sender_ids()
    assert result["items"][0]["sender_id"] == "MYAPP"


@respx.mock
async def test_list_email_domains(client):
    respx.get(f"{BASE}/email/domains").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "d1", "domain": "example.com", "status": "verified"}]})
    )
    result = await client.list_email_domains()
    assert result == [{"id": "d1", "domain": "example.com", "status": "verified"}]


@respx.mock
async def test_list_email_senders(client):
    respx.get(f"{BASE}/email/senders").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "s1", "email": "no-reply@example.com"}]})
    )
    result = await client.list_email_senders()
    assert result == [{"id": "s1", "email": "no-reply@example.com"}]


@respx.mock
async def test_send_email_maps_from_and_strips_nones(client):
    import json

    route = respx.post(f"{BASE}/email/send").mock(
        return_value=httpx.Response(202, json={"data": {"id": "e1", "status": "queued"}})
    )
    result = await client.send_email(
        to="customer@example.com",
        from_email="no-reply@example.com",
        subject="Hello",
        text="Hi there",
    )
    assert result == {"id": "e1", "status": "queued"}

    sent = json.loads(route.calls[0].request.content)
    assert sent["from"] == "no-reply@example.com"  # from_email → "from" key
    assert sent["to"] == "customer@example.com"
    assert sent["text"] == "Hi there"
    assert "html" not in sent          # None values stripped by _request
    assert "cc" not in sent
    assert "bcc" not in sent
    assert "schedule_at" not in sent


@respx.mock
async def test_send_email_with_cc_bcc_and_schedule(client):
    import json

    route = respx.post(f"{BASE}/email/send").mock(
        return_value=httpx.Response(202, json={"data": {"id": "e2", "status": "scheduled"}})
    )
    await client.send_email(
        to="a@example.com",
        from_email="noreply@example.com",
        subject="Bulk",
        html="<p>Hi</p>",
        cc=["b@example.com"],
        bcc=["c@example.com"],
        schedule_at="2026-07-01T09:00:00Z",
        tags=["promo"],
    )
    sent = json.loads(route.calls[0].request.content)
    assert sent["cc"] == ["b@example.com"]
    assert sent["bcc"] == ["c@example.com"]
    assert sent["schedule_at"] == "2026-07-01T09:00:00Z"
    assert sent["tags"] == ["promo"]


@respx.mock
async def test_send_email_empty_lists_excluded(client):
    """Empty cc/bcc lists must not be sent (they become None and are stripped)."""
    import json

    route = respx.post(f"{BASE}/email/send").mock(
        return_value=httpx.Response(202, json={"data": {"id": "e3"}})
    )
    await client.send_email(
        to="x@example.com",
        from_email="y@example.com",
        subject="Test",
        text="body",
        cc=[],   # empty list → None → stripped
        bcc=[],
    )
    sent = json.loads(route.calls[0].request.content)
    assert "cc" not in sent
    assert "bcc" not in sent
