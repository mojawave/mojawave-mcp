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
