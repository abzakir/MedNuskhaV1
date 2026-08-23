"""Verify editing a running course and deleting a medicine."""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(r"C:\Users\ASUS\Desktop\MedNuskha")
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import select

from app.config import Settings
from app.db import session_scope
from app.models import DoseEvent, Medicine, MessageLog, Schedule

OK, BAD = [], []


def check(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          + (f"   -> {detail}" if detail and not cond else ""))


s = Settings()
tok = httpx.post(f"{s.supabase_url.rstrip('/')}/auth/v1/token?grant_type=password",
                 headers={"apikey": s.supabase_anon_key},
                 json={"email": "mednuskha.demo@gmail.com",
                       "password": "MedNuskha2026!"}, timeout=30).json()["access_token"]
c = httpx.Client(base_url="http://127.0.0.1:8000",
                 headers={"Authorization": f"Bearer {tok}"}, timeout=90)

pid = c.get("/api/patients").json()[0]["id"]

print("=== setup: a fresh medicine at 08:00, 7 days")
r = c.post("/api/medicines", json={
    "patient_id": pid, "name": "Brufen", "strength": "400mg",
    "dose_times": ["08:00"], "duration_days": 7,
    "purpose_ur": "dard ke liye", "food_rule": "Khane ke baad lein.", "edited": True})
check("created", r.status_code == 201, r.text[:150])
mid = r.json()["id"]

with session_scope() as db:
    sched = db.exec(select(Schedule).where(Schedule.medicine_id == mid)).first()
    before = db.exec(select(DoseEvent).where(
        DoseEvent.schedule_id == sched.id)).all()
print(f"     {len(before)} doses materialised")

print("\n=== A. change the times")
r = c.patch(f"/api/medicines/{mid}",
            json={"dose_times": ["09:30", "21:30"], "duration_days": 7})
check("edit accepted", r.status_code == 200, r.text[:200])
body = r.json()
check("times updated and sorted",
      body["dose_times"] == ["09:30", "21:30"], body["dose_times"])
print(f"     {body['doses_removed']} old doses dropped, {body['doses_created']} created")

detail = c.get(f"/api/patients/{pid}").json()
med = [m for m in detail["medicines"] if m["id"] == mid][0]
check("dashboard shows the new times",
      med["schedule"]["dose_times"] == ["09:30", "21:30"], med["schedule"])

with session_scope() as db:
    sched = db.exec(select(Schedule).where(Schedule.medicine_id == mid)).first()
    doses = db.exec(select(DoseEvent).where(DoseEvent.schedule_id == sched.id)).all()
    from app.config import settings as cfg
    hhmm = {d.scheduled_at.replace(tzinfo=timezone.utc).astimezone(cfg.tz).strftime("%H:%M")
            for d in doses if d.state == "SCHEDULED"}
check("no 08:00 doses left waiting", "08:00" not in hhmm, sorted(hhmm))
check("both new times present", {"09:30", "21:30"} <= hhmm, sorted(hhmm))

print("\n=== B. change the course length")
r = c.patch(f"/api/medicines/{mid}",
            json={"dose_times": ["09:30", "21:30"], "duration_days": 14})
check("length changed", r.status_code == 200, r.text[:150])
detail = c.get(f"/api/patients/{pid}").json()
med = [m for m in detail["medicines"] if m["id"] == mid][0]
check("now 14 days", med["schedule"]["duration_days"] == 14, med["schedule"])
check("14 days remaining", med["schedule"]["days_remaining"] == 14,
      med["schedule"]["days_remaining"])
check("end_date still inclusive",
      date.fromisoformat(med["schedule"]["end_date"])
      == date.fromisoformat(med["schedule"]["start_date"]) + timedelta(days=13),
      med["schedule"])

print("\n=== C. history is never rewritten")
with session_scope() as db:
    sched = db.exec(select(Schedule).where(Schedule.medicine_id == mid)).first()
    dose = db.exec(select(DoseEvent).where(DoseEvent.schedule_id == sched.id)
                   .where(DoseEvent.state == "SCHEDULED")).first()
    dose.state = "TAKEN"
    dose.responded_at = datetime.now(timezone.utc)
    dose.response_text = "haan le li"
    db.add(dose); db.commit()
    kept_id, kept_at = dose.id, dose.scheduled_at

r = c.patch(f"/api/medicines/{mid}",
            json={"dose_times": ["07:00"], "duration_days": 14})
check("edit accepted again", r.status_code == 200, r.text[:150])
with session_scope() as db:
    still = db.get(DoseEvent, kept_id)
check("an ANSWERED dose survives a time change", still is not None and still.state == "TAKEN",
      still.state if still else "deleted")
check("its reply is untouched",
      still and still.response_text == "haan le li", still.response_text if still else None)

print("\n=== D. stop keeps the history")
r = c.delete(f"/api/medicines/{mid}")
check("stop works", r.status_code == 200 and r.json()["deleted"] is False, r.text[:120])
detail = c.get(f"/api/patients/{pid}").json()
med = [m for m in detail["medicines"] if m["id"] == mid][0]
check("still listed, marked inactive", med["active"] is False, med["active"])
with session_scope() as db:
    check("its doses are still there",
          len(db.exec(select(DoseEvent).where(DoseEvent.id == kept_id)).all()) == 1)

print("\n=== E. delete removes it for real")
with session_scope() as db:
    # a message referencing one of its doses, to prove messages survive
    db.add(MessageLog(wa_message_id="EDIT.TEST.1", direction="out", kind="text",
                      patient_id=pid, dose_event_id=kept_id, body="test"))
    db.commit()

r = c.delete(f"/api/medicines/{mid}?permanent=true")
check("delete works", r.status_code == 200 and r.json()["deleted"] is True, r.text[:150])
print(f"     {r.json().get('doses_removed')} doses removed")

detail = c.get(f"/api/patients/{pid}").json()
check("gone from the dashboard",
      not any(m["id"] == mid for m in detail["medicines"]),
      [m["name"] for m in detail["medicines"]])
with session_scope() as db:
    check("medicine row gone", db.get(Medicine, mid) is None)
    check("its doses gone", db.get(DoseEvent, kept_id) is None)
    msg = db.exec(select(MessageLog).where(
        MessageLog.wa_message_id == "EDIT.TEST.1")).first()
    check("the message it sent is KEPT, just unlinked",
          msg is not None and msg.dose_event_id is None,
          "message was deleted" if msg is None else msg.dose_event_id)
    if msg:
        db.delete(msg); db.commit()

print("\n=== F. another family cannot edit or delete")
r = c.patch("/api/medicines/00000000-0000-0000-0000-000000000000",
            json={"dose_times": ["08:00"], "duration_days": 7})
check("unknown medicine -> 404", r.status_code == 404, r.status_code)

c.close()
print(f"\n{'=' * 58}\n  {len(OK)} passed, {len(BAD)} failed")
for f in BAD:
    print(f"    FAILED: {f}")
sys.exit(1 if BAD else 0)
