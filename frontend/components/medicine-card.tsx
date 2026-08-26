"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AdherenceNumber } from "@/components/status-pill";
import { api, type MedicineDetail } from "@/lib/api";

const COMMON_TIMES = ["08:00", "13:00", "20:00", "22:00"];
const TENURES = [7, 14, 30];

export function MedicineCard({
  medicine,
  patientId,
  onChange,
}: {
  medicine: MedicineDetail;
  patientId: string;
  onChange: () => void;
}) {
  const s = medicine.schedule;

  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const [times, setTimes] = useState<string[]>(s?.dose_times ?? []);
  const [days, setDays] = useState<number>(s?.duration_days ?? 7);
  const [strength, setStrength] = useState(medicine.strength ?? "");

  function toggleTime(t: string) {
    setTimes((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t].sort(),
    );
  }

  async function openReport(kind: "doctor" | "caretaker") {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      await api.openReport(patientId, kind, medicine.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function startEditing() {
    setTimes(s?.dose_times ?? []);
    setDays(s?.duration_days ?? 7);
    setStrength(medicine.strength ?? "");
    setError(null);
    setNote(null);
    setEditing(true);
  }

  async function save() {
    if (times.length === 0) {
      setError("Pick at least one time.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.updateMedicine(medicine.id, {
        dose_times: times,
        duration_days: days,
        strength: strength || undefined,
      });
      setNote(
        r.doses_removed > 0
          ? `Updated. ${r.doses_removed} upcoming dose${
              r.doses_removed === 1 ? "" : "s"
            } rescheduled.`
          : "Updated.",
      );
      setEditing(false);
      onChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
      setConfirmDelete(false);
    }
  }

  return (
    <div className="rounded-xl border bg-card p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="font-medium">
            {medicine.name}
            {medicine.strength && (
              <span className="ml-1.5 text-muted-foreground">{medicine.strength}</span>
            )}
            {!medicine.active && (
              <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                stopped
              </span>
            )}
          </h3>

          {s && !editing && (
            <p className="mt-1 text-sm text-muted-foreground">
              <span className="font-mono">{s.dose_times.join(", ")}</span> ·{" "}
              {s.duration_days} days
              {s.finished ? (
                <span className="ml-1.5 text-taken">
                  · course complete
                </span>
              ) : (
                <span className="ml-1.5">
                  · {s.days_remaining} {s.days_remaining === 1 ? "day" : "days"} left
                </span>
              )}
            </p>
          )}

          {medicine.info?.purpose_ur && !editing && (
            <p className="mt-2 max-w-prose text-sm">
              {medicine.info.purpose_ur}
              {medicine.info.food_rule && (
                <span className="text-muted-foreground">
                  {" "}
                  — {medicine.info.food_rule}
                </span>
              )}
            </p>
          )}
        </div>

        <div className="text-right">
          <AdherenceNumber percent={medicine.adherence.percent} size="sm" />
          <p className="text-[11px] text-muted-foreground">
            {medicine.adherence.taken}/{medicine.adherence.decided} taken
          </p>
        </div>
      </div>

      {/* ------------------------------------------------------- editor */}
      {editing && (
        <div className="mt-4 space-y-4 rounded-lg border bg-muted/30 p-4">
          <div>
            <Label className="text-xs">Times of day</Label>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {Array.from(new Set([...COMMON_TIMES, ...times]))
                .sort()
                .map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => toggleTime(t)}
                    className={`rounded-full border px-3.5 py-1.5 font-mono text-sm transition-colors ${ times.includes(t)
                        ? "border-taken/40 bg-taken-soft text-taken"
                        : "bg-background hover:bg-muted"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              <Input
                type="time"
                className="w-32"
                onChange={(e) => {
                  const v = e.target.value;
                  if (v && !times.includes(v)) setTimes([...times, v].sort());
                }}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-6">
            <div>
              <Label className="text-xs">Course length</Label>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {TENURES.map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setDays(d)}
                    className={`rounded-full border px-3.5 py-1.5 text-sm transition-colors ${ days === d
                        ? "border-taken/40 bg-taken-soft text-taken"
                        : "bg-background hover:bg-muted"
                    }`}
                  >
                    {d} days
                  </button>
                ))}
                <Input
                  type="number"
                  min={1}
                  max={365}
                  value={TENURES.includes(days) ? "" : days}
                  onChange={(e) => setDays(Number(e.target.value) || 1)}
                  placeholder="Custom"
                  className="w-24"
                />
              </div>
            </div>

            <div>
              <Label className="text-xs" htmlFor={`strength-${medicine.id}`}>
                Strength
              </Label>
              <Input
                id={`strength-${medicine.id}`}
                value={strength}
                onChange={(e) => setStrength(e.target.value)}
                placeholder="500mg"
                className="mt-2 w-28"
              />
            </div>
          </div>

          <p className="text-xs text-muted-foreground">
            Doses already sent or answered stay exactly as they are — only upcoming
            ones move.
          </p>

          {error && <ErrorLine message={error} />}

          <div className="flex gap-2">
            <Button size="sm" onClick={save} disabled={busy}>
              {busy ? "Saving…" : "Save changes"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setEditing(false)}
              disabled={busy}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      {/* -------------------------------------------- stats and actions */}
      {!editing && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t pt-3">
          <div className="flex gap-4 text-xs text-muted-foreground">
            {medicine.adherence.decided > 0 ? (
              <>
                <span>{medicine.adherence.on_time} on time</span>
                {medicine.adherence.late > 0 && (
                  <span>{medicine.adherence.late} late</span>
                )}
                {medicine.adherence.missed > 0 && (
                  <span className="text-missed">
                    {medicine.adherence.missed} missed
                  </span>
                )}
              </>
            ) : (
              <span>No doses answered yet.</span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-1">
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => openReport("doctor")}
              title="One-page clinical summary of this course, for the doctor"
            >
              Doctor report
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => openReport("caretaker")}
              title="A plain-language summary of how this course went"
            >
              Your report
            </Button>
            <span className="mx-1 h-4 w-px bg-border" aria-hidden />
            <Button size="sm" variant="outline" onClick={startEditing} disabled={busy}>
              Edit times
            </Button>
            {medicine.active && (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => act(() => api.stopMedicine(medicine.id))}
                title="Stop reminders but keep the history for reports"
              >
                Stop
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              className="text-missed hover:bg-missed-soft hover:text-missed"
              disabled={busy}
              onClick={() => setConfirmDelete(true)}
            >
              Delete
            </Button>
          </div>
        </div>
      )}

      {note && !editing && (
        <p className="mt-3 rounded-lg bg-taken-soft p-2.5 text-xs text-taken">
          {note}
        </p>
      )}
      {error && !editing && (
        <div className="mt-3">
          <ErrorLine message={error} />
        </div>
      )}

      {/* ------------------------------------------- delete confirmation */}
      {confirmDelete && (
        <div className="mt-3 rounded-lg border border-missed/40 bg-missed-soft p-4">
          <p className="text-sm font-medium text-missed">
            Delete {medicine.name} completely?
          </p>
          <p className="mt-1 text-sm text-missed">
            This removes its dose history too, so it won&apos;t appear in any report.
            {medicine.adherence.decided > 0 && (
              <>
                {" "}
                <strong>
                  {medicine.adherence.decided} answered dose
                  {medicine.adherence.decided === 1 ? "" : "s"} will be lost.
                </strong>
              </>
            )}{" "}
            If the course simply finished, use <strong>Stop</strong> instead — that
            keeps the record.
          </p>
          <div className="mt-3 flex gap-2">
            <Button
              size="sm"
              variant="destructive"
              disabled={busy}
              onClick={() => act(() => api.deleteMedicine(medicine.id))}
            >
              {busy ? "Deleting…" : "Yes, delete it"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setConfirmDelete(false)}
              disabled={busy}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function ErrorLine({ message }: { message: string }) {
  return (
    <p className="rounded-lg bg-missed-soft p-2.5 text-xs text-missed">
      {message}
    </p>
  );
}
