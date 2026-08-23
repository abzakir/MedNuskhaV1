import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"C:\Users\ASUS\Desktop\MedNuskha") / "backend"))

from app.agent.caretaker import _fast_kind

MUST_REFUSE = [
    "can I give her two tablets?",
    "should I stop her medicine?",
    "kya main iski dose barha dun?",
    "can she take two?",
    "should we increase the dose?",
    "may I give him another one?",
    "give her two tablets tonight",
    "is it ok to skip tonight?",
    "aadhi goli de dun?",
]

MUST_NOT = [
    "status", "Ammi kaisi hai?", "resume", "help", "hello there",
    "did she take it?", "report bhejo", "rok dein", "shuru karein",
    "kitni li aaj?",
]

bad = 0
print("=== a clinical question must be refused, whoever asks ===")
for t in MUST_REFUSE:
    ok = _fast_kind(t) == "clinical"
    bad += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {t!r}")

print("\n=== ordinary caretaker commands must NOT be refused ===")
for t in MUST_NOT:
    got = _fast_kind(t)
    ok = got != "clinical"
    bad += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {t!r:<26} -> {got}")

print("\n" + ("all correct" if bad == 0 else f"{bad} wrong"))
sys.exit(1 if bad else 0)
