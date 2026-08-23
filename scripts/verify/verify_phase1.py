"""Phase 1 verification against the live Supabase database.

Covers everything in the Phase 1 gate that does not need a real phone:
parser shapes, number normalisation, webhook verify handshake, message_log
persistence, and the wa_message_id deduplication.
"""

import sys, os
from pathlib import Path

ROOT = Path(r"C:\Users\ASUS\Desktop\MedNuskha")
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_verify_token_123")

from app.config import get_settings
get_settings.cache_clear()
from app.config import settings
settings.whatsapp_verify_token = "test_verify_token_123"

from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import session_scope
from app.main import app
from app.models import DoseEvent, Family, Medicine, MessageLog, Patient, Schedule
from app.whatsapp.client import normalise_number
from app.whatsapp.parser import parse_statuses, parse_webhook

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('  -> ' + str(detail)) if detail and not cond else ''}")


def envelope(msg=None, statuses=None):
    value = {"messaging_product": "whatsapp",
             "metadata": {"display_phone_number": "15550001111",
                          "phone_number_id": "999888777"}}
    if msg:
        value["contacts"] = [{"profile": {"name": "Test"}, "wa_id": msg["from"]}]
        value["messages"] = [msg]
    if statuses:
        value["statuses"] = statuses
    return {"object": "whatsapp_business_account",
            "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": value}]}]}


NUM = "923009998877"
DOSE = "11111111-2222-3333-4444-555555555555"

print("\n=== 1. number normalisation (section 10: digits only, no + or leading 0)")
for raw, want in [("+92 300 999-8877", "923009998877"),
                  ("03009998877", "923009998877"),
                  ("00923009998877", "923009998877"),
                  ("923009998877", "923009998877")]:
    got = normalise_number(raw)
    check(f"{raw!r} -> {want}", got == want, got)

print("\n=== 2. parser: all four inbound shapes")
m = parse_webhook(envelope({"from": NUM, "id": "wamid.TEXT", "timestamp": "1755870000",
                            "type": "text", "text": {"body": "haan le li"}}))[0]
check("text -> kind=text, body captured", m.kind == "text" and m.text == "haan le li", m)

m = parse_webhook(envelope({"from": NUM, "id": "wamid.BTN", "timestamp": "1755870001",
                            "type": "button",
                            "button": {"text": "Le li", "payload": f"TAKEN:{DOSE}"}}))[0]
check("TEMPLATE button -> kind=button, payload carries dose id",
      m.kind == "button" and m.payload == f"TAKEN:{DOSE}", m)

m = parse_webhook(envelope({"from": NUM, "id": "wamid.INT", "timestamp": "1755870002",
                            "type": "interactive",
                            "interactive": {"type": "button_reply",
                                            "button_reply": {"id": f"LATER:{DOSE}",
                                                             "title": "Abhi nahi"}}}))[0]
check("INTERACTIVE button_reply -> same kind=button, id as payload",
      m.kind == "button" and m.payload == f"LATER:{DOSE}", m)

m = parse_webhook(envelope({"from": NUM, "id": "wamid.AUD", "timestamp": "1755870003",
                            "type": "audio",
                            "audio": {"id": "MEDIA123", "mime_type": "audio/ogg; codecs=opus",
                                      "voice": True}}))[0]
check("audio -> kind=audio, media_id captured",
      m.kind == "audio" and m.media_id == "MEDIA123", m)

m = parse_webhook(envelope({"from": NUM, "id": "wamid.IMG", "timestamp": "1755870004",
                            "type": "image",
                            "image": {"id": "IMG9", "caption": "nuskha"}}))[0]
check("image -> kind=other, still captured for Phase 7", m.kind == "other" and m.media_id == "IMG9", m)

st = parse_statuses(envelope(statuses=[{"id": "wamid.OUT1", "status": "delivered",
                                        "timestamp": "1755870005", "recipient_id": NUM}]))
check("status update parsed", len(st) == 1 and st[0].status == "delivered", st)
check("status-only payload yields no messages", parse_webhook(envelope(statuses=[{"id": "x", "status": "read", "timestamp": "1"}])) == [])

print("\n=== 3. webhook GET verify (must be PLAIN TEXT, not JSON)")
c = TestClient(app)
r = c.get("/webhook", params={"hub.mode": "subscribe",
                              "hub.verify_token": "test_verify_token_123",
                              "hub.challenge": "CHALLENGE_42"})
check("correct token -> 200", r.status_code == 200, r.status_code)
check("returns raw challenge, unquoted", r.text == "CHALLENGE_42", repr(r.text))
check("content-type is text/plain", r.headers["content-type"].startswith("text/plain"),
      r.headers.get("content-type"))
r = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "wrong",
                              "hub.challenge": "X"})
check("wrong token -> 403", r.status_code == 403, r.status_code)

print("\n=== 4. seed a patient in the live database")
with session_scope() as s:
    fam = s.exec(select(Family).where(Family.name == "PHASE1 VERIFY")).first()
    if not fam:
        fam = Family(name="PHASE1 VERIFY"); s.add(fam); s.commit(); s.refresh(fam)
    pat = s.exec(select(Patient).where(Patient.whatsapp_number == NUM)).first()
    if not pat:
        pat = Patient(family_id=fam.id, name="Verify Patient",
                      whatsapp_number=NUM, language="ur", opted_in=True)
        s.add(pat); s.commit(); s.refresh(pat)
    med = Medicine(patient_id=pat.id, name="Panadol", strength="500mg")
    s.add(med); s.commit(); s.refresh(med)
    from datetime import date, datetime, timedelta, timezone
    sch = Schedule(medicine_id=med.id, dose_times=["08:00", "20:00"], duration_days=7,
                   start_date=date.today(), end_date=date.today() + timedelta(days=6))
    s.add(sch); s.commit(); s.refresh(sch)
    when = datetime.now(timezone.utc)
    dose = DoseEvent(schedule_id=sch.id, patient_id=pat.id, scheduled_at=when,
                     idempotency_key=f"{sch.id}:{when.isoformat()}", state="AWAITING_REPLY")
    s.add(dose); s.commit(); s.refresh(dose)
    fam_id, pat_id, med_id, sch_id, dose_id = fam.id, pat.id, med.id, sch.id, dose.id
DOSE = dose_id
print(f"  patient {pat_id} on {NUM}")
print(f"  real dose_event {DOSE}")

print("\n=== 5. POST /webhook: 200 fast, then persist")
body = envelope({"from": NUM, "id": "wamid.VERIFY.001", "timestamp": "1755870010",
                 "type": "button", "button": {"text": "Le li", "payload": f"TAKEN:{DOSE}"}})
import time
t0 = time.time(); r = c.post("/webhook", json=body); elapsed = time.time() - t0
check("POST returns 200", r.status_code == 200, r.status_code)
check(f"returned in {elapsed*1000:.0f}ms (invariant 3: under 2s)", elapsed < 2.0, elapsed)

with session_scope() as s:
    rows = s.exec(select(MessageLog).where(MessageLog.wa_message_id == "wamid.VERIFY.001")).all()
check("exactly one message_log row written", len(rows) == 1, len(rows))
if rows:
    row = rows[0]
    check("direction=in, kind=button", row.direction == "in" and row.kind == "button")
    check("button payload persisted", row.payload == f"TAKEN:{DOSE}", row.payload)
    check("dose_event_id extracted from payload (invariant 2)", row.dose_event_id == DOSE, row.dose_event_id)
    check("linked to the right patient", row.patient_id == pat_id, row.patient_id)
    check("raw Meta payload kept for debugging", isinstance(row.raw, dict))

print("\n=== 6. DEDUPLICATION - deliver the SAME payload again (invariant 4)")
r = c.post("/webhook", json=body)
check("duplicate still returns 200", r.status_code == 200, r.status_code)
with session_scope() as s:
    n = len(s.exec(select(MessageLog).where(MessageLog.wa_message_id == "wamid.VERIFY.001")).all())
check("STILL exactly one row, not two", n == 1, f"{n} rows")

print("\n=== 7. status receipt updates the outbound row")
with session_scope() as s:
    s.add(MessageLog(wa_message_id="wamid.OUTBOUND.T1", direction="out", kind="template",
                     patient_id=pat_id, to_number=NUM, template_name="dose_reminder",
                     status="sent"))
    s.commit()
c.post("/webhook", json=envelope(statuses=[{"id": "wamid.OUTBOUND.T1", "status": "read",
                                            "timestamp": "1755870020", "recipient_id": NUM}]))
with session_scope() as s:
    row = s.exec(select(MessageLog).where(MessageLog.wa_message_id == "wamid.OUTBOUND.T1")).first()
check("outbound row now status=read", row and row.status == "read", row.status if row else None)

print("\n=== 8. cleanup")
with session_scope() as s:
    for r_ in s.exec(select(MessageLog).where(MessageLog.patient_id == pat_id)).all():
        s.delete(r_)
    s.commit()
    for model, ident in ((DoseEvent, dose_id), (Schedule, sch_id), (Medicine, med_id),
                         (Patient, pat_id), (Family, fam_id)):
        obj = s.get(model, ident)
        if obj: s.delete(obj)
        s.commit()
print("  test rows removed")

print(f"\n{'='*60}\n  {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL: print(f"    FAILED: {f}")
sys.exit(1 if FAIL else 0)
