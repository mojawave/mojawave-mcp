"""Live smoke test for the MojaWave MCP client against the real API.

Exercises the read-mostly public endpoints to confirm they behave as documented.
It sends ONE real bulk SMS of a single recipient (your own number) — that costs
1 credit and delivers a real message. Skip the send with --no-send.

    export MOJAWAVE_API_KEY="mw_live_..."   # or sk_live_mw_...
    export MOJAWAVE_TEST_TO="+255XXXXXXXXX" # your own phone, E.164
    python examples/live_smoketest.py            # full run (sends 1 SMS)
    python examples/live_smoketest.py --no-send  # credits-only, no send
"""

from __future__ import annotations

import asyncio
import os
import sys

from mojawave_mcp.client import MojaWaveClient, MojaWaveError


async def main(send: bool) -> None:
    to = os.environ.get("MOJAWAVE_TEST_TO")
    api_key = os.environ.get("MOJAWAVE_API_KEY")
    if not api_key:
        sys.exit("Set MOJAWAVE_API_KEY.")
    if send and not to:
        sys.exit("Set MOJAWAVE_TEST_TO (or pass --no-send).")

    async with MojaWaveClient(api_key=api_key) as client:
        # 1. Credits (GET /credits) — proves auth + envelope unwrap.
        bal = await client.get_credit_balance()
        sms = bal.get("sms", {})
        print(f"✓ /credits        -> sms balance: {sms.get('balance')}")

        if not send:
            print("Skipping send (--no-send).")
            return
        if (sms.get("balance") or 0) < 1:
            print("Not enough credits to test a send.")
            return

        # 2. Bulk send of one recipient (POST /sms/bulk) -> job_id.
        job = await client.send_bulk_sms(
            recipients=[to],
            message="MojaWave MCP live smoke test.",
            sender_id="MojaWave",
            name="mcp-smoketest",
        )
        job_id = job.get("id") or job.get("job_id")
        print(f"✓ /sms/bulk       -> job {job_id} status={job.get('status')}")

        # 3. Poll the bulk job (GET /sms/bulk/{id}).
        for _ in range(6):
            await asyncio.sleep(3)
            status = await client.get_bulk_sms_job(job_id)
            print(f"  /sms/bulk/{{id}} -> status={status.get('status')} "
                  f"progress={status.get('progress_percent')}")
            if status.get("status") in ("completed", "failed"):
                break


if __name__ == "__main__":
    asyncio.run(main(send="--no-send" not in sys.argv))
