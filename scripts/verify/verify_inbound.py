"""Inbound path: the bridge's exact payload shape through webhook -> dose."""
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# scripts/verify/<this file> -> scripts/verify -> scripts -> <repo root>
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

from fastapi.testclient import TestClient
from sqlmodel import select

from app.config import settings
from app.db import session_scope
from app.main import app
from app.models import (Caretaker, DoseEvent, Family, Medicine, MessageLog,
                        Patient, Schedule)

OK, BAD = [], []
NUM = "923009990001"
SECRET = settings.webhook_secret


def check(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          + (f"   -> {detail}" if detail and not cond else ""))


def cleanup():
    with session_scope() as s:
        pat = s.exec(select(Patient).where(Patient.whatsapp_number == NUM)).first()
        if pat:
            for r in s.exec(select(MessageLog).where(MessageLog.patient_id == pat.id)).all():
                s.delete(r)
            for d in s.exec(select(DoseEvent).where(DoseEvent.patient_id == pat.id)).all():
                s.delete(d)
            s.commit()
            for m in s.exec(select(Medicine).where(Medicine.patient_id == pat.id)).all():
                for sc in s.exec(select(Schedule).where(Schedule.medicine_id == m.id)).all():
                    s.delete(sc)
                s.commit(); s.delete(m)
            s.commit()
            fam = pat.family_id
            s.delete(pat); s.commit()
            for c in s.exec(select(Caretaker).where(Caretaker.family_id == fam)).all():
                s.delete(c)
            s.commit()
            f = s.get(Family, fam)
            if f: s.delete(f)
            s.commit()


cleanup()

with session_scope() as s:
    fam = Family(name="INBOUND VERIFY"); s.add(fam); s.commit(); s.refresh(fam)
    care = Caretaker(family_id=fam.id, name="Zakir", phone="923009990002", relation="beta")
    pat = Patient(family_id=fam.id, name="Ammi", whatsapp_number=NUM, opted_in=True)
    s.add(care); s.add(pat); s.commit(); s.refresh(pat)
    med = Medicine(patient_id=pat.id, name="Panadol", strength="500mg")
    s.add(med); s.commit(); s.refresh(med)
    sch = Schedule(medicine_id=med.id, dose_times=["08:00"], duration_days=7,
                   start_date=date.today(), end_date=date.today() + timedelta(days=6))
    s.add(sch); s.commit(); s.refresh(sch)
    when = datetime.now(timezone.utc)
    dose = DoseEvent(schedule_id=sch.id, patient_id=pat.id, scheduled_at=when,
                     idempotency_key=f"{sch.id}:{when.isoformat()}",
                     state="AWAITING_REPLY", sent_at=when)
    s.add(dose); s.commit(); s.refresh(dose)
    pat_id, dose_id = pat.id, dose.id

print(f"  seeded patient {pat_id}, dose {dose_id} in AWAITING_REPLY\n")
c = TestClient(app)


def bridge_post(payload, secret=SECRET):
    path = f"/webhook/{secret}" if secret else "/webhook"
    return c.post(path, json=payload)


def state():
    with session_scope() as s:
        d = s.get(DoseEvent, dose_id)
        return d.state if d else None


print("=== webhook secret is enforced")
r = c.post("/webhook/wrong-secret", json={"id": "x", "from": NUM, "type": "text"})
check("wrong secret -> 403", r.status_code == 403, r.status_code)
r = c.post("/webhook", json={"id": "x", "from": NUM, "type": "text"})
check("missing secret -> 403", r.status_code == 403, r.status_code)
r = c.get("/webhook")
check("GET /webhook is a plain liveness check", r.status_code == 200, r.status_code)

print("\n=== a typed text reply from the bridge")
r = bridge_post({"id": "BRIDGE.TXT.1", "from": NUM, "timestamp": 1755870000,
                 "type": "text", "text": "haan le li hai", "raw": {"contentType": "conversation"}})
check("accepted with 200", r.status_code == 200, r.status_code)
with session_scope() as s:
    row = s.exec(select(MessageLog).where(MessageLog.wa_message_id == "BRIDGE.TXT.1")).first()
check("persisted to message_log", row is not None)
check("linked to the patient", row and row.patient_id == pat_id)
check("text captured verbatim", row and row.body == "haan le li hai", row.body if row else None)

print("\n=== deduplication on the bridge's message id")
bridge_post({"id": "BRIDGE.TXT.1", "from": NUM, "timestamp": 1755870000,
             "type": "text", "text": "haan le li hai"})
with session_scope() as s:
    n = len(s.exec(select(MessageLog).where(MessageLog.wa_message_id == "BRIDGE.TXT.1")).all())
check("redelivery does NOT create a second row", n == 1, f"{n} rows")

print("\n=== a button-style reply carrying the dose id (invariant 2)")
r = bridge_post({"id": "BRIDGE.BTN.1", "from": NUM, "timestamp": 1755870005,
                 "type": "button", "buttonId": f"TAKEN:{dose_id}", "text": "Le li"})
check("accepted", r.status_code == 200, r.status_code)
check("dose moved to TAKEN", state() == "TAKEN", state())
with session_scope() as s:
    row = s.exec(select(MessageLog).where(MessageLog.wa_message_id == "BRIDGE.BTN.1")).first()
    check("message_log links to the dose", row and row.dose_event_id == dose_id,
          row.dose_event_id if row else None)
    d = s.get(DoseEvent, dose_id)
    check("response_source recorded as button", d.response_source == "button", d.response_source)

print("\n=== an inbound voice note arrives with its audio attached")
import base64
fake_audio = base64.b64encode(b"OggS" + b"\x00" * 200).decode()
r = bridge_post({"id": "BRIDGE.AUD.1", "from": NUM, "timestamp": 1755870010,
                 "type": "audio", "audioBase64": fake_audio,
                 "raw": {"contentType": "audioMessage", "ptt": True}})
check("accepted", r.status_code == 200, r.status_code)
from app.whatsapp.parser import parse_webhook
msgs = parse_webhook({"id": "X", "from": NUM, "type": "audio", "audioBase64": fake_audio})
check("parser decodes the audio inline (no second fetch)",
      msgs and msgs[0].media_bytes and msgs[0].media_bytes.startswith(b"OggS"))
check("kind is audio", msgs and msgs[0].kind == "audio")

print("\n=== a message from an unknown number is ignored, not crashed on")
r = bridge_post({"id": "BRIDGE.UNKNOWN", "from": "923999999999",
                 "timestamp": 1755870020, "type": "text", "text": "salam"})
check("still 200", r.status_code == 200, r.status_code)

cleanup()
print("\n  cleaned up")
print(f"\n{'=' * 58}\n  {len(OK)} passed, {len(BAD)} failed")
for f in BAD:
    print(f"    FAILED: {f}")
sys.exit(1 if BAD else 0)
