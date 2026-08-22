"""CLI: send a real WhatsApp message to one number. The Phase 1 gate.

    python scripts/send_test.py 923001234567
    python scripts/send_test.py 03001234567 --medicine "Panadol 500mg" --time 8
    python scripts/send_test.py 923001234567 --text "salam, test"

The default sends the `dose_reminder` template with both quick-reply buttons.
Tapping one delivers TAKEN:<dose_id> or LATER:<dose_id> to the webhook, which
writes a message_log row carrying that payload.

If the templates are not approved yet, use --text. Free-form text only
delivers inside an open 24-hour window, so message the test number from your
phone first (AGENTS.md section 17).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# Runnable as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import settings  # noqa: E402
from app.whatsapp.client import (  # noqa: E402
    WhatsAppError,
    close_client,
    normalise_number,
    send_template,
    send_text,
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="send_test.py",
        description="Send a test WhatsApp message through the Cloud API.",
    )
    ap.add_argument("number", help="recipient, e.g. 923001234567 or 03001234567")
    ap.add_argument("--template", default="dose_reminder", help="template name")
    ap.add_argument("--lang", default=None,
                    help="template language code as submitted to Meta "
                         "(default: en)")
    ap.add_argument("--name", default="Abdul", help="patient name, variable 1")
    ap.add_argument("--time", default="8", help="hour, variable 2")
    ap.add_argument("--medicine", default="Panadol 500mg",
                    help="medicine and strength, variable 3")
    ap.add_argument("--note", default="Khane ke baad lein.",
                    help="food rule, variable 4")
    ap.add_argument("--dose-id", default=None,
                    help="dose id for the button payloads (default: random)")
    ap.add_argument("--text", default=None,
                    help="send this plain text instead of a template")
    return ap


async def run(args: argparse.Namespace) -> int:
    missing = [n for n, v in (
        ("WHATSAPP_TOKEN", settings.whatsapp_token),
        ("WHATSAPP_PHONE_NUMBER_ID", settings.whatsapp_phone_number_id),
    ) if not v]
    if missing:
        print(f"! {', '.join(missing)} not set in .env", file=sys.stderr)
        print("  See MedNuskha_Setup_Guide.pdf, section 2.", file=sys.stderr)
        return 2

    to = normalise_number(args.number)
    print(f"  sending to  {to}")
    print(f"  from        phone_number_id {settings.whatsapp_phone_number_id}")
    print(f"  api         {settings.whatsapp_api_version}")

    try:
        if args.text:
            print(f"  type        text\n")
            wamid = await send_text(to, args.text)
        else:
            dose_id = args.dose_id or str(uuid.uuid4())
            payloads = [f"TAKEN:{dose_id}", f"LATER:{dose_id}"]
            print(f"  type        template {args.template}")
            print(f"  dose id     {dose_id}")
            print(f"  buttons     {payloads[0]}")
            print(f"              {payloads[1]}\n")
            wamid = await send_template(
                to=to,
                template=args.template,
                lang=args.lang or "en",
                body_vars=[args.name, args.time, args.medicine, args.note],
                button_payloads=payloads,
            )
    except WhatsAppError as exc:
        print(f"FAILED  {exc}", file=sys.stderr)
        print("\nCommon causes:", file=sys.stderr)
        print("  131030  recipient is not on the 5-number whitelist", file=sys.stderr)
        print("  132001  template name or language does not match Meta",
              file=sys.stderr)
        print("  190     token expired - use the permanent System User token",
              file=sys.stderr)
        return 1
    finally:
        await close_client()

    print(f"SENT    wa_message_id {wamid}")
    print("\nNow tap a button on the phone and check message_log for the payload.")
    return 0


def main(argv: list[str]) -> int:
    return asyncio.run(run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
