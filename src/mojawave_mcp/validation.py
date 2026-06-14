"""Lightweight input validation for tool arguments.

Each validator raises :class:`ValueError` with a clear, model-readable message so
the assistant can correct the input instead of firing a doomed API call.
"""

from __future__ import annotations

import re
from datetime import datetime

# E.164: leading +, country digit 1-9, then up to 14 more digits.
_E164 = re.compile(r"^\+[1-9]\d{6,14}$")
# Sender ID: 1-11 alphanumeric characters (telco rule for alphanumeric IDs).
_SENDER_ID = re.compile(r"^[A-Za-z0-9]{1,11}$")
# Email: simplified RFC-5321 local@domain.tld — catches obvious malformed
# addresses without being a ReDoS vector. The API does the authoritative check.
_EMAIL = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

MAX_MESSAGE_CHARS = 1600
MAX_BULK_RECIPIENTS = 10_000
MAX_SUBJECT_CHARS = 500


def validate_phone(phone: str) -> str:
    phone = phone.strip()
    if not _E164.match(phone):
        raise ValueError(
            f"'{phone}' is not a valid E.164 phone number. "
            "Use the format +255712345678 (leading + and country code)."
        )
    return phone


def validate_sender_id(sender_id: str) -> str:
    sender_id = sender_id.strip()
    if not _SENDER_ID.match(sender_id):
        raise ValueError(
            f"'{sender_id}' is not a valid sender ID. "
            "Use 1-11 alphanumeric characters (e.g. MYAPP or MojaWave)."
        )
    return sender_id


def validate_message(message: str) -> str:
    if not message or not message.strip():
        raise ValueError("message must not be empty.")
    if len(message) > MAX_MESSAGE_CHARS:
        raise ValueError(
            f"message is {len(message)} characters; the maximum is {MAX_MESSAGE_CHARS}."
        )
    return message


def validate_recipients(recipients: list[str]) -> list[str]:
    if not recipients:
        raise ValueError("recipients must contain at least one phone number.")
    if len(recipients) > MAX_BULK_RECIPIENTS:
        raise ValueError(
            f"{len(recipients)} recipients exceeds the maximum of {MAX_BULK_RECIPIENTS}."
        )
    return [validate_phone(r) for r in recipients]


def validate_schedule_at(value: str) -> str:
    """Validate an ISO-8601 timestamp; return it unchanged if valid."""

    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"'{value}' is not a valid ISO-8601 timestamp. "
            "Use e.g. 2026-06-15T09:00:00Z."
        ) from exc
    return value


def validate_email_address(email: str) -> str:
    email = email.strip()
    if not _EMAIL.match(email):
        raise ValueError(
            f"'{email}' is not a valid email address. "
            "Use the format user@example.com."
        )
    return email


def validate_email_subject(subject: str) -> str:
    subject = subject.strip()
    if not subject:
        raise ValueError("subject must not be empty.")
    if len(subject) > MAX_SUBJECT_CHARS:
        raise ValueError(
            f"subject is {len(subject)} characters; the maximum is {MAX_SUBJECT_CHARS}."
        )
    return subject
