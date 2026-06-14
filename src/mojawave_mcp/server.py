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
        "You are connected to MojaWave, a unified messaging platform for Tanzania. "
        "You can send single and bulk SMS, send transactional email, look up "
        "message and bulk-job status, and check credit balances. "
        "Phone numbers must be in E.164 format (e.g. +255712345678). "
        "For SMS, call list_sms_sender_ids first to discover which sender IDs are "
        "approved and available. If the list is empty or the user has no approved "
        "sender IDs yet, use 'MojaWave' as the default shared sender ID — it is "
        "always available as a fallback. "
        "For email, call list_email_domains and list_email_senders first to confirm "
        "which domains are verified and which from_email addresses are registered "
        "before attempting send_email. "
        "ALWAYS confirm the recipient(s), content, and sender with the user before "
        "calling send_sms, send_bulk_sms, or send_email — these spend real credits "
        "and deliver real messages."
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
    return json.dumps(result, indent=2, default=str)


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
    sender_id: str,
    schedule_at: str = "",
) -> str:
    """Send a single SMS message, optionally scheduled for future delivery.

    Confirm recipient, message, and sender_id with the user first — this spends
    real credits.

    Args:
        to: Recipient phone number in E.164 format (e.g. +255712345678).
        message: SMS text content (max 1600 characters).
        sender_id: Sender ID shown to the recipient (1-11 alphanumeric chars,
            e.g. MYAPP). Use list_sms_sender_ids to find approved IDs. If none
            exist, use 'MojaWave' as the default shared sender ID.
        schedule_at: Optional future delivery time in ISO-8601 UTC
            (e.g. 2026-06-15T09:00:00Z). Leave empty to send immediately.
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
    sender_id: str,
    name: str = "",
) -> str:
    """Send the same SMS to up to 10,000 recipients. Processed asynchronously —
    returns a job_id immediately; use get_bulk_sms_job to track progress.

    Confirm the recipient list size, message, and sender_id with the user first —
    this spends real credits.

    Args:
        recipients: List of phone numbers in E.164 format (1-10,000).
        message: SMS text content (max 1600 characters).
        sender_id: Sender ID (1-11 alphanumeric chars). Use list_sms_sender_ids
            to find approved IDs, or 'MojaWave' as the default fallback.
        name: Optional campaign name for your reference (e.g. "June Promo").
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
    """List approved SMS sender IDs available on your account.

    Returns IDs with status "approved". If the list is empty, the user has
    no custom sender IDs yet — use 'MojaWave' as the default shared sender
    ID, which is always available as a fallback.
    Call this before sending to pick the correct sender ID.
    """
    try:
        result = await _client().list_sms_sender_ids()
        return _fmt(result)
    except Exception as e:  # noqa: BLE001
        return _err(e)


@mcp.tool()
async def get_bulk_sms_job(job_id: str) -> str:
    """Get the status and progress of a bulk SMS job.

    Args:
        job_id: The job UUID returned by send_bulk_sms.
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
    """Get full details and delivery status (timeline) for a single message.

    Args:
        message_id: The UUID of the message returned when it was sent.
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
    """Get current SMS and email credit balances for your organization."""
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
    """Verify a MojaWave webhook's HMAC-SHA256 signature.

    Pass the RAW request body (exactly as received), the value of the
    X-MojaWave-Signature header, and your webhook signing secret. Returns whether
    the signature is valid — only act on webhook events that verify as valid.

    Args:
        payload: The raw webhook request body (do not re-serialize it).
        signature: The X-MojaWave-Signature header value.
        secret: Your webhook signing secret (whsec_...).
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
    """List all email sending domains registered on your account.

    Call this before send_email to confirm which domains are verified and
    available. Only domains with status "verified" can send mail.
    """
    try:
        result = await _client().list_email_domains()
        return _fmt(result)
    except Exception as e:  # noqa: BLE001
        return _err(e)


@mcp.tool()
async def list_email_senders() -> str:
    """List all registered sender addresses available for sending email.

    Returns the email addresses you can use in the from_email field of
    send_email. Each sender belongs to a verified domain.
    """
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
    """Send a transactional email from a registered sender address.

    Costs 1 credit per recipient (to + each cc + each bcc).
    At least one of body (plain text) or html is required.

    Call list_email_senders first to confirm from_email is registered.
    ALWAYS confirm to, subject, from_email, and body/html with the user
    before sending — this spends real credits and delivers a real email.

    Args:
        to: Recipient email address (e.g. customer@example.com).
        from_email: Registered sender address on a verified domain
            (e.g. noreply@yourdomain.com). Use list_email_senders to find
            valid values.
        subject: Email subject line (max 500 chars).
        body: Plain-text body. At least one of body or html is required.
        html: Optional HTML body (e.g. "<p>Hello</p>"). Provide alongside
            body as a fallback for clients that don't render HTML.
        from_name: Optional display name shown in the recipient's inbox
            (e.g. "Duka Masta Billing").
        cc: Optional list of CC addresses. Each costs 1 credit.
        bcc: Optional list of BCC addresses. Each costs 1 credit.
        reply_to: Optional reply-to address if different from from_email.
        schedule_at: Optional future delivery time in ISO-8601
            (e.g. 2026-06-15T09:00:00Z). Naive datetimes (no Z/offset) are
            treated as EAT (Africa/Dar_es_Salaam, UTC+3). Leave empty to
            send immediately.
        tags: Optional string labels for filtering in message history
            (max 10).
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
