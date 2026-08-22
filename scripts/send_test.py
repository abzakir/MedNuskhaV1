"""CLI: send a real WhatsApp message to one number. The Phase 1 gate.

    python scripts/send_test.py 923001234567
    python scripts/send_test.py 03001234567 --medicine "Panadol 500mg" --time 8
    python scripts/send_test.py 923001234567 --text "salam, test"
    python scripts/send_test.py 923001234567 --voice

Sends through the local Baileys bridge, so the bridge must be running:

    .\\bridge.ps1        (or: make bridge)

There is no template approval and no 24-hour window on this transport - the
copy is rendered from app/i18n/strings.py and sent immediately.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import settings  # noqa: E402
from app.whatsapp.client import (  # noqa: E402
    WhatsAppError,
    bridge_status,
    close_client,
    normalise_number,
    render,
    send_template,
    send_text,
    send_voice,
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="send_test.py",
        description="Send a test WhatsApp message through the Baileys bridge.")
    ap.add_argument("number", help="recipient, e.g. 923001234567 or 03001234567")
    ap.add_argument("--template", default="dose_reminder",
                    help="dose_reminder / dose_followup / caretaker_alert / patient_optin")
    ap.add_argument("--lang", default="ur", help="ur or en")
    ap.add_argument("--name", default="Ammi", help="patient name")
    ap.add_argument("--time", default="8", help="hour")
    ap.add_argument("--medicine", default="Panadol 500mg", help="medicine and strength")
    ap.add_argument("--note", default="Khane ke baad lein.", help="food rule")
    ap.add_argument("--dose-id", default=None, help="dose id for the reply payload")
    ap.add_argument("--text", default=None, help="send this plain text instead")
    ap.add_argument("--voice", action="store_true",
                    help="also send the message as an Urdu voice note")
    return ap


async def synth_ogg(text: str) -> bytes:
    """edge-tts -> OGG/Opus mono, which is what WhatsApp plays (invariant 7)."""
    import av
    import edge_tts

    mp3 = io.BytesIO()
    async for chunk in edge_tts.Communicate(text, settings.tts_voice).stream():
        if chunk["type"] == "audio":
            mp3.write(chunk["data"])

    src = av.open(io.BytesIO(mp3.getvalue()))
    buf = io.BytesIO()
    dst = av.open(buf, mode="w", format="ogg")
    stream = dst.add_stream("libopus", rate=48000)
    stream.layout = "mono"
    resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
    for frame in src.decode(audio=0):
        for rframe in resampler.resample(frame):
            for packet in stream.encode(rframe):
                dst.mux(packet)
    for packet in stream.encode(None):
        dst.mux(packet)
    dst.close()
    src.close()
    return buf.getvalue()


async def run(args: argparse.Namespace) -> int:
    status = await bridge_status()
    state = status.get("state")
    print(f"  bridge      {settings.bridge_url}  ({state})")

    if state != "connected":
        print(f"\n! WhatsApp is not connected (state: {state}).", file=sys.stderr)
        if state == "qr":
            print("  Scan the QR code shown in the bridge terminal.", file=sys.stderr)
        elif state == "unreachable":
            print("  Start the bridge:  .\\bridge.ps1", file=sys.stderr)
        return 2

    to = normalise_number(args.number)
    print(f"  from        {status.get('me')}")
    print(f"  sending to  {to}")

    try:
        if args.text:
            print("  type        plain text\n")
            print(f"  {args.text}\n")
            mid = await send_text(to, args.text)
        else:
            dose_id = args.dose_id or str(uuid.uuid4())
            payloads = [f"TAKEN:{dose_id}", f"LATER:{dose_id}"]
            body = render(args.template, args.lang,
                          [args.name, args.time, args.medicine, args.note])
            print(f"  type        {args.template} ({args.lang})")
            print(f"  dose id     {dose_id}\n")
            print(f"  {body}\n")
            mid = await send_template(to=to, template=args.template, lang=args.lang,
                                      body_vars=[args.name, args.time,
                                                 args.medicine, args.note],
                                      button_payloads=payloads)

        print(f"SENT    {mid}")

        if args.voice:
            print("\n  synthesising the Urdu voice note ...")
            text = (f"{args.name} ji, {args.time} baj gaye. "
                    f"{args.medicine} lene ka waqt hai.")
            ogg = await synth_ogg(text)
            print(f"  {len(ogg):,} bytes of OGG/Opus")
            vid = await send_voice(to, ogg)
            print(f"SENT    voice note {vid}")

    except WhatsAppError as exc:
        print(f"FAILED  {exc}", file=sys.stderr)
        return 1
    finally:
        await close_client()

    print("\nNow reply from that phone and watch the backend log.")
    return 0


def main(argv: list[str]) -> int:
    return asyncio.run(run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
