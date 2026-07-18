"""MojaWave MCP server.

Exposes the MojaWave **public** v1 API as MCP tools: send single & bulk SMS,
look up messages and bulk jobs, check credit balances, and verify webhook
signatures. Nothing outside the documented public API is exposed.

Run with stdio (default):
    mojawave-mcp

Run with HTTP/SSE transport (hosted):
    mojawave-mcp --transport sse --port 8080
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from mojawave_mcp.client import DEFAULT_BASE_URL, MojaWaveClient, MojaWaveError
from mojawave_mcp.validation import (
    validate_email_address,
    validate_email_subject,
    validate_message,
    validate_phone,
    validate_recipients,
    validate_schedule_at,
    validate_sender_id,
)
from mojawave_mcp.webhooks import verify_signature

load_dotenv()

mcp = FastMCP(
    "MojaWave",
    instructions=(
        "MojaWave messaging API for Tanzania. Phone numbers must be E.164 (e.g. +255712345678). "
        "SMS: call list_sms_sender_ids first; if empty use sender_id='MojaWave' (always available). "
        "Email: call list_email_domains + list_email_senders first to pick a verified from_email. "
        "ALWAYS confirm recipient, content, and sender with the user before send_sms, send_bulk_sms, or send_email."
    ),
)

# Module-level singleton — created lazily, reuses one httpx connection pool.
_client_instance: MojaWaveClient | None = None


def _client() -> MojaWaveClient:
    global _client_instance
    if _client_instance is None:
        api_key = os.environ.get("MOJAWAVE_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "MOJAWAVE_API_KEY is not set. Add it to your environment or .env file."
            )
        base_url = os.environ.get("MOJAWAVE_BASE_URL", DEFAULT_BASE_URL)
        _client_instance = MojaWaveClient(api_key=api_key, base_url=base_url)
    return _client_instance


def _fmt(result: dict) -> str:
    return json.dumps(result, default=str)


def _err(e: Exception) -> str:
    """Render an exception as a concise, model-readable error string."""

    if isinstance(e, ValueError):
        return f"Invalid input: {e}"
    if isinstance(e, MojaWaveError):
        rid = f" (request_id: {e.request_id})" if e.request_id else ""
        return f"MojaWave error [{e.code or e.status_code}]: {e.detail}{rid}"
    if isinstance(e, RuntimeError):
        return f"Configuration error: {e}"
    return f"Unexpected error: {e}"


# ---------------------------------------------------------------------------
# SMS
# ---------------------------------------------------------------------------


@mcp.tool()
async def send_sms(
    to: str,
    message: str,
    sender_id: str = "MojaWave",
    schedule_at: str = "",
) -> str:
    """Send a single SMS. Confirm with user before calling — spends real credits.

    Args:
        to: Recipient in E.164 format (e.g. +255712345678).
        message: SMS text (max 1600 chars).
        sender_id: Sender ID (default: MojaWave). Use list_sms_sender_ids to find approved IDs.
        schedule_at: ISO-8601 UTC delivery time, or empty to send immediately.
    """
    try:
        to = validate_phone(to)
        message = validate_message(message)
        sender_id = validate_sender_id(sender_id)
        scheduled = validate_schedule_at(schedule_at) if schedule_at else None
        result = await _client().send_sms(
            to=to, message=message, sender_id=sender_id, schedule_at=scheduled
        )
        return _fmt(result)
    except Exception as e:  # noqa: BLE001 - surfaced to the model as text
        return _err(e)


@mcp.tool()
async def send_bulk_sms(
    recipients: list[str],
    message: str,
    sender_id: str = "MojaWave",
    name: str = "",
) -> str:
    """Send bulk SMS to up to 10,000 recipients. Returns job_id; poll with get_bulk_sms_job. Confirm with user first — spends real credits.

    Args:
        recipients: E.164 phone numbers (1–10,000).
        message: SMS text (max 1600 chars).
        sender_id: Sender ID (default: MojaWave). Use list_sms_sender_ids to find approved IDs.
        name: Optional campaign name.
    """
    try:
        recipients = validate_recipients(recipients)
        message = validate_message(message)
        sender_id = validate_sender_id(sender_id)
        result = await _client().send_bulk_sms(
            recipients=recipients,
            message=message,
            sender_id=sender_id,
            name=name or None,
        )
        return _fmt(result)
    except Exception as e:  # noqa: BLE001
        return _err(e)


@mcp.tool()
async def list_sms_sender_ids() -> str:
    """List approved SMS sender IDs. If empty, use 'MojaWave' as the default shared sender ID."""
    try:
        result = await _client().list_sms_sender_ids()
        return _fmt(result)
    except Exception as e:  # noqa: BLE001
        return _err(e)


@mcp.tool()
async def get_bulk_sms_job(job_id: str) -> str:
    """Get status and progress of a bulk SMS job.

    Args:
        job_id: UUID returned by send_bulk_sms.
    """
    try:
        if not job_id.strip():
            raise ValueError("job_id must not be empty.")
        result = await _client().get_bulk_sms_job(job_id.strip())
        return _fmt(result)
    except Exception as e:  # noqa: BLE001
        return _err(e)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_message(message_id: str) -> str:
    """Get delivery status and timeline for a message.

    Args:
        message_id: UUID returned when the message was sent.
    """
    try:
        if not message_id.strip():
            raise ValueError("message_id must not be empty.")
        result = await _client().get_message(message_id.strip())
        return _fmt(result)
    except Exception as e:  # noqa: BLE001
        return _err(e)


# ---------------------------------------------------------------------------
# Credits
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_credit_balance() -> str:
    """Get current SMS and email credit balances."""
    try:
        result = await _client().get_credit_balance()
        return _fmt(result)
    except Exception as e:  # noqa: BLE001
        return _err(e)


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


@mcp.tool()
async def verify_webhook_signature(payload: str, signature: str, secret: str) -> str:
    """Verify a webhook's X-MojaWave-Signature (HMAC-SHA256) locally — no API call.

    Args:
        payload: Raw request body (do not parse first).
        signature: X-MojaWave-Signature header value.
        secret: Webhook signing secret.
    """
    try:
        valid = verify_signature(payload, signature, secret)
        return _fmt({"valid": valid})
    except Exception as e:  # noqa: BLE001
        return _err(e)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_email_domains() -> str:
    """List email sending domains. Only "verified" domains can send mail."""
    try:
        result = await _client().list_email_domains()
        return _fmt(result)
    except Exception as e:  # noqa: BLE001
        return _err(e)


@mcp.tool()
async def list_email_senders() -> str:
    """List registered sender addresses usable as from_email in send_email."""
    try:
        result = await _client().list_email_senders()
        return _fmt(result)
    except Exception as e:  # noqa: BLE001
        return _err(e)


@mcp.tool()
async def send_email(
    to: str,
    from_email: str,
    subject: str,
    body: str = "",
    html: str = "",
    from_name: str = "",
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    reply_to: str = "",
    schedule_at: str = "",
    tags: list[str] | None = None,
) -> str:
    """Send a transactional email. Confirm with user first — spends real credits.

    Args:
        to: Recipient email address.
        from_email: Registered sender (use list_email_senders to find valid values).
        subject: Subject line (max 500 chars).
        body: Plain-text body (required if html is empty).
        html: HTML body (required if body is empty).
        from_name: Optional display name.
        cc: Optional CC addresses (1 credit each).
        bcc: Optional BCC addresses (1 credit each).
        reply_to: Optional reply-to address.
        schedule_at: ISO-8601 delivery time, or empty to send now.
        tags: Optional labels for filtering (max 10).
    """
    try:
        to = validate_email_address(to)
        from_email = validate_email_address(from_email)
        subject = validate_email_subject(subject)

        text = body.strip() if body.strip() else None
        html_body = html.strip() if html.strip() else None
        if not text and not html_body:
            raise ValueError("At least one of body or html is required.")

        validated_cc = [validate_email_address(a) for a in cc] if cc else None
        validated_bcc = [validate_email_address(a) for a in bcc] if bcc else None
        reply = validate_email_address(reply_to) if reply_to.strip() else None
        scheduled = validate_schedule_at(schedule_at) if schedule_at.strip() else None

        result = await _client().send_email(
            to=to,
            from_email=from_email,
            subject=subject,
            text=text,
            html=html_body,
            from_name=from_name.strip() or None,
            reply_to=reply,
            cc=validated_cc,
            bcc=validated_bcc,
            schedule_at=scheduled,
            tags=tags if tags else None,
        )
        return _fmt(result)
    except Exception as e:  # noqa: BLE001
        return _err(e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MojaWave MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport to use (default: stdio)",
    )
    parser.add_argument("--port", type=int, default=8080, help="Port for SSE (default: 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="Host for SSE (default: 0.0.0.0)")
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
