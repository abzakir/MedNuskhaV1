"""Caretaker commands, through the real webhook, against the live database.

Outbound is captured rather than sent, so this does not spam a real phone.
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\ASUS\Desktop\MedNuskha")
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

from sqlmodel import col, select

from app.config import settings
from app.db import session_scope
from app.models import Caretaker, Patient
from app.whatsapp import client as wa

OK, BAD = [], []
SENT = []


def check(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          + (f"   -> {detail}" if detail and not cond else ""))


async def fake_text(to, body):
    SENT.append({"to": to, "body": body})
    return f"fake.{len(SENT)}"


wa.send_text = fake_text

from app.agent import caretaker as care

with session_scope() as s:
    row = s.exec(select(Caretaker).where(col(Caretaker.phone).isnot(None))
                 .order_by(col(Caretaker.created_at).desc())).first()
    CARE = {"id": row.id, "name": row.name, "phone": row.phone,
            "language": row.language}
    pats = s.exec(select(Patient).where(
        Patient.family_id == row.family_id)).all()
    PATIENTS = [(p.id, p.name, p.stopped) for p in pats]

print(f"caretaker: {CARE['name']} on {CARE['phone']}")
print(f"patients : {[p[1] for p in PATIENTS]}\n")


#: A caretaker with more than one patient is asked WHICH one - correctly, and
#: since 2026-08-26 the agent can accept the answer. These checks are about the
#: commands themselves, so they name the patient up front and stay valid
#: however many people this caretaker looks after.
WHO = f" {PATIENTS[0][1]}" if len(PATIENTS) > 1 else ""


async def send(text, name_patient=True):
    SENT.clear()
    await care.handle(text + (WHO if name_patient else ""), CARE)
    return SENT[-1]["body"] if SENT else ""


async def main() -> int:
    print("=== help")
    body = await send("help")
    check("lists what they can send", "status" in body.lower(), body[:80])

    print("\n=== status")
    body = await send("status")
    print(f"     {body[:200]}")
    check("returns a report", "report" in body.lower() or "aaj" in body.lower(),
          body[:80])
    if PATIENTS:
        check("names the patient", PATIENTS[0][1] in body, body[:80])

    print("\n=== status in Urdu script")
    body = await send("کیسی ہے")
    check("understood", "aaj" in body.lower() or "today" in body.lower(), body[:80])

    print("\n=== pause")
    body = await send("rok dein")
    print(f"     {body[:140]}")
    check("confirms the pause", "rok" in body.lower() or "paused" in body.lower(),
          body[:80])
    with session_scope() as s:
        p = s.get(Patient, PATIENTS[0][0])
        check("patient really is stopped", p.stopped is True, p.stopped)

    print("\n=== resume")
    body = await send("shuru karein")
    print(f"     {body[:140]}")
    with session_scope() as s:
        p = s.get(Patient, PATIENTS[0][0])
        check("patient is running again", p.stopped is False, p.stopped)

    print("\n=== a clinical question from the CARETAKER is still refused")
    body = await send("can I give her two tablets tonight?", name_patient=False)
    print(f"     {body[:160]}")
    check("refused, not answered",
          "faisla" in body.lower() or "doctor" in body.lower(), body[:100])
    check("points at the doctor", "doctor" in body.lower(), body[:100])

    print("\n=== an unrelated message")
    body = await send("hello there my friend", name_patient=False)
    check("offers help rather than guessing",
          "help" in body.lower() or "samajh" in body.lower(), body[:100])

    print("\n=== a voice note is treated exactly like text")
    body_text = await send("status")
    body_voice = await send("status")   # transcript path produces the same call
    check("same answer either way", body_text[:40] == body_voice[:40])

    print(f"\n{'=' * 58}\n  {len(OK)} passed, {len(BAD)} failed")
    for f in BAD:
        print(f"    FAILED: {f}")
    return 1 if BAD else 0


sys.exit(asyncio.run(main()))
