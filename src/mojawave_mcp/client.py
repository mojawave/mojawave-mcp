"""Secure, reliable async HTTP client for the MojaWave **public** REST API.

Implements only the documented v1 endpoints:

    POST /sms/send            — send a single SMS
    GET  /messages/{id}       — message details & delivery status
    POST /sms/bulk            — bulk send (async job)
    GET  /sms/bulk/{jobId}    — bulk job status
    GET  /sms/sender-ids/approved — list approved SMS sender IDs (slim)
    GET  /credits             — SMS & email credit balances
    GET  /email/domains       — list verified sending domains
    GET  /email/senders       — list registered sender addresses
    POST /email/send          — send a transactional email

Reliability:
  * Retries 429 and 5xx with exponential backoff + jitter, honouring
    ``Retry-After`` / ``X-RateLimit-Reset``.
  * Per-request timeout, connection pooling via a single AsyncClient.
  * Unwraps the ``{"success": true, "data": …}`` envelope.

Security:
  * Sends both ``Authorization: Bearer`` and ``X-API-Key`` (both accepted).
  * Maps documented HTTP statuses to typed errors; never echoes the raw key.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.mojawave.com/v1"

# Documented error codes by HTTP status (used as a fallback when the API body
# omits a machine-readable code).
_STATUS_CODES = {
    400: "invalid_request",
    401: "unauthorized",
    402: "insufficient_balance",
    422: "unprocessable",
    429: "rate_limit_exceeded",
    500: "server_error",
}


class MojaWaveError(Exception):
    """Raised when the MojaWave API returns a non-2xx response.

    Attributes:
        status_code: HTTP status (or ``None`` for transport failures).
        code: Machine-readable error code (e.g. ``insufficient_balance``).
        detail: Human-readable message.
        request_id: ``X-Request-Id`` header, when present.
    """

    def __init__(
        self,
        status_code: int | None,
        code: str | None,
        detail: str,
        request_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.request_id = request_id
        super().__init__(f"MojaWave API error {status_code} ({code}): {detail}")


class MojaWaveClient:
    """Async client wrapping the MojaWave v1 public REST API.

    Holds a single ``httpx.AsyncClient`` for connection pooling. Call
    :meth:`aclose` (or use as an async context manager) for clean teardown.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._http = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {api_key}",
                "X-API-Key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "mojawave-mcp/0.3.0",
            },
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "MojaWaveClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Transport with retry + envelope unwrap
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict:
        url = f"{self._base_url}{path}"
        body = None if json is None else {k: v for k, v in json.items() if v is not None}
        query = None if params is None else {k: v for k, v in params.items() if v is not None}

        attempt = 0
        while True:
            try:
                resp = await self._http.request(method, url, json=body, params=query)
            except httpx.TimeoutException as exc:
                raise MojaWaveError(None, "timeout", f"Request timed out: {exc}") from exc
            except httpx.RequestError as exc:
                raise MojaWaveError(None, "connection_error", f"Could not reach MojaWave: {exc}") from exc

            if resp.is_success:
                return self._unwrap(resp)

            retryable = resp.status_code == 429 or resp.status_code >= 500
            if retryable and attempt < self._max_retries:
                attempt += 1
                await asyncio.sleep(self._backoff(resp, attempt))
                continue

            raise self._error(resp)

    @staticmethod
    def _unwrap(resp: httpx.Response) -> dict:
        try:
            data = resp.json()
        except ValueError:
            return {"raw": resp.text[:500]}
        # Unwrap the standard envelope so tools see the resource directly.
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    def _error(self, resp: httpx.Response) -> MojaWaveError:
        code: str | None = None
        message = f"HTTP {resp.status_code}"
        try:
            body = resp.json()
            if isinstance(body, dict):
                nested = body.get("error") if isinstance(body.get("error"), dict) else body
                code = nested.get("code") or body.get("code")
                message = nested.get("message") or body.get("message") or message
        except ValueError:
            text = resp.text.strip()
            if text:
                message = text[:300]
        if code is None:
            code = _STATUS_CODES.get(resp.status_code)
        return MojaWaveError(
            resp.status_code,
            code,
            message,
            request_id=resp.headers.get("X-Request-Id"),
        )

    def _backoff(self, resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 30.0)
            except ValueError:
                pass
        reset = resp.headers.get("X-RateLimit-Reset")
        if reset:
            try:
                import time

                delta = int(reset) - int(time.time())
                if delta > 0:
                    return min(float(delta), 30.0)
            except ValueError:
                pass
        # Exponential backoff with full jitter: base 0.5s, capped at 8s.
        return random.uniform(0, min(8.0, 0.5 * (2 ** attempt)))

    # ------------------------------------------------------------------
    # SMS
    # ------------------------------------------------------------------

    async def send_sms(
        self,
        to: str,
        message: str,
        sender_id: str,
        *,
        schedule_at: str | None = None,
        webhook_url: str | None = None,
    ) -> dict:
        return await self._request("POST", "/sms/send", json={
            "to": to,
            "from": sender_id,
            "message": message,
            "schedule_at": schedule_at,
            "webhook_url": webhook_url,
        })

    async def send_bulk_sms(
        self,
        recipients: list[str],
        message: str,
        sender_id: str,
        *,
        name: str | None = None,
        webhook_url: str | None = None,
    ) -> dict:
        return await self._request("POST", "/sms/bulk", json={
            "name": name,
            "from": sender_id,
            "message": message,
            "recipients": [{"to": r} for r in recipients],
            "webhook_url": webhook_url,
        })

    async def get_bulk_sms_job(self, job_id: str) -> dict:
        return await self._request("GET", f"/sms/bulk/{job_id}")

    async def list_sms_sender_ids(self) -> dict:
        return await self._request("GET", "/sms/sender-ids/approved")

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def get_message(self, message_id: str) -> dict:
        return await self._request("GET", f"/messages/{message_id}")

    # ------------------------------------------------------------------
    # Credits
    # ------------------------------------------------------------------

    async def get_credit_balance(self) -> dict:
        return await self._request("GET", "/credits")

    # ------------------------------------------------------------------
    # Email
    # ------------------------------------------------------------------

    async def list_email_domains(self) -> dict:
        return await self._request("GET", "/email/domains")

    async def list_email_senders(self) -> dict:
        return await self._request("GET", "/email/senders")

    async def send_email(
        self,
        to: str,
        from_email: str,
        subject: str,
        *,
        text: str | None = None,
        html: str | None = None,
        from_name: str | None = None,
        reply_to: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        schedule_at: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        return await self._request("POST", "/email/send", json={
            "to": to,
            "from": from_email,
            "subject": subject,
            "text": text,
            "html": html,
            "from_name": from_name,
            "reply_to": reply_to,
            "cc": cc if cc else None,
            "bcc": bcc if bcc else None,
            "schedule_at": schedule_at,
            "tags": tags if tags else None,
            "metadata": metadata,
        })
