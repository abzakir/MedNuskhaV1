"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { MedicineCard } from "@/components/medicine-card";
import { StatusPill } from "@/components/status-pill";
import {
  api,
  type Dose,
  type EventRow,
  type PatientDetail,
  type Today,
} from "@/lib/api";

export default function PatientPage() {
  const { id } = useParams<{ id: string }>();
  const [patient, setPatient] = useState<PatientDetail | null>(null);
  const [today, setToday] = useState<Today | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [optinSent, setOptinSent] = useState(false);
  const [resuming, setResuming] = useState(false);

  const loadPatient = useCallback(
    () => api.patient(id).then(setPatient).catch((e) => setError((e as Error).message)),
    [id],
  );

  useEffect(() => {
    loadPatient();
  }, [loadPatient]);

  // Section 14: poll today's doses every 5 seconds while the page is open.
  useEffect(() => {
    let alive = true;
    const tick = () => {
      api.today(id).then((t) => alive && setToday(t)).catch(() => {});
      api.events(id).then((e) => alive && setEvents(e)).catch(() => {});
    };
    tick();
    const timer = setInterval(tick, 5_000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [id]);

  if (error) {
    return (
      <p className="rounded-lg bg-rose-50 p-4 text-sm text-rose-900 dark:bg-rose-950/50 dark:text-rose-200">
        {error}
      </p>
    );
  }
  if (!patient) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-8">
      <div>
        <Link
          href="/dashboard"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          &larr; All patients
        </Link>

        <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{patient.name}</h1>
            <p className="mt-0.5 font-mono text-sm text-muted-foreground">
              +{patient.whatsapp_number}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                api
                  .sendOptin(id)
                  .then(() => setOptinSent(true))
                  .catch((e) => setError((e as Error).message))
              }
              disabled={optinSent}
            >
              {optinSent ? "Intro sent ✓" : "Send intro message"}
            </Button>
            <Button asChild size="sm">
              <Link href={`/dashboard/patients/${id}/medicines/new`}>Add medicine</Link>
            </Button>
          </div>
        </div>
      </div>

      {patient.stopped && (
        <div className="rounded-lg border border-rose-300 bg-rose-50 p-4 dark:border-rose-900 dark:bg-rose-950/40">
          <p className="text-sm text-rose-900 dark:text-rose-200">
            <strong className="font-medium">
              Reminders are stopped for {patient.name}.
            </strong>{" "}
            They replied something we read as STOP, so nothing is being sent. If that
            was a misunderstanding, start them again.
          </p>
          <Button
            size="sm"
            className="mt-3"
            disabled={resuming}
            onClick={async () => {
              setResuming(true);
              try {
                await api.resumePatient(id);
                await loadPatient();
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setResuming(false);
              }
            }}
          >
            {resuming ? "Starting…" : "Start reminders again"}
          </Button>
        </div>
      )}

      {/* ------------------------------------------------ today */}
      <section>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-lg font-medium">Today</h2>
          {today && (
            <span className="text-xs text-muted-foreground">
              live · {today.server_time}
            </span>
          )}
        </div>

        <div className="overflow-hidden rounded-xl border bg-card">
          {!today || today.doses.length === 0 ? (
            <p className="p-8 text-center text-sm text-muted-foreground">
              {patient.medicines.length === 0
                ? "No medicines yet. Add one and reminders start straight away."
                : "No doses due today."}
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-4 py-2.5 text-left font-medium">Time</th>
                  <th className="px-4 py-2.5 text-left font-medium">Medicine</th>
                  <th className="px-4 py-2.5 text-left font-medium">Status</th>
                  <th className="px-4 py-2.5 text-left font-medium">They said</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {today.doses.map((dose) => (
                  <DoseRow key={dose.id} dose={dose} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {/* ------------------------------------------------ medicines */}
      <section>
        <h2 className="mb-3 text-lg font-medium">Medicines</h2>
        {patient.medicines.length === 0 ? (
          <div className="rounded-xl border border-dashed bg-card p-8 text-center">
            <p className="text-sm text-muted-foreground">
              Add a medicine to start reminders.
            </p>
            <Button asChild className="mt-4" size="sm">
              <Link href={`/dashboard/patients/${id}/medicines/new`}>Add medicine</Link>
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            {patient.medicines.map((m) => (
              <MedicineCard key={m.id} medicine={m} onChange={loadPatient} />
            ))}
          </div>
        )}
      </section>

      {/* ------------------------------------------------ log */}
      <section>
        <h2 className="mb-3 text-lg font-medium">Activity</h2>
        <div className="rounded-xl border bg-card">
          {events.length === 0 ? (
            <p className="p-8 text-center text-sm text-muted-foreground">
              Nothing yet.
            </p>
          ) : (
            <ul className="divide-y">
              {events.slice(0, 30).map((e, i) => (
                <EventItem key={`${e.at}-${i}`} event={e} />
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}

function DoseRow({ dose }: { dose: Dose }) {
  return (
    <tr className="hover:bg-muted/30">
      <td className="whitespace-nowrap px-4 py-3 font-mono tabular-nums">{dose.time}</td>
      <td className="px-4 py-3 font-medium">{dose.medicine}</td>
      <td className="px-4 py-3">
        <StatusPill state={dose.state} />
        {dose.caretaker_alerted && (
          <span className="ml-2 text-xs text-muted-foreground">you were alerted</span>
        )}
      </td>
      <td className="max-w-[16rem] px-4 py-3 text-muted-foreground">
        {dose.response_text ? (
          <span className="italic">&ldquo;{dose.response_text}&rdquo;</span>
        ) : dose.reason ? (
          <span className="italic">&ldquo;{dose.reason}&rdquo;</span>
        ) : (
          <span className="text-muted-foreground/50">—</span>
        )}
        {dose.response_source === "voice" && (
          <span className="ml-1 text-xs">🎤</span>
        )}
      </td>
    </tr>
  );
}

function EventItem({ event }: { event: EventRow }) {
  const time = new Date(event.at).toLocaleString([], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

  if (event.kind === "symptom") {
    return (
      <li className="flex gap-3 px-4 py-3 text-sm">
        <span className="w-28 shrink-0 text-xs text-muted-foreground">{time}</span>
        <span
          className={`shrink-0 rounded px-1.5 py-0.5 text-xs ${
            event.severity === "emergency"
              ? "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300"
              : "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300"
          }`}
        >
          {event.severity === "emergency" ? "urgent" : "symptom"}
        </span>
        <span className="italic">&ldquo;{event.body}&rdquo;</span>
      </li>
    );
  }

  const inbound = event.direction === "in";
  return (
    <li className="flex gap-3 px-4 py-3 text-sm">
      <span className="w-28 shrink-0 text-xs text-muted-foreground">{time}</span>
      <span
        className={`shrink-0 text-xs ${
          inbound ? "text-teal-700 dark:text-teal-400" : "text-muted-foreground"
        }`}
      >
        {inbound ? "they said" : "we sent"}
      </span>
      <span className="min-w-0 flex-1 truncate text-muted-foreground">
        {event.body ?? event.template ?? event.type}
      </span>
      {event.status === "failed" && (
        <span className="shrink-0 text-xs text-rose-600 dark:text-rose-400">failed</span>
      )}
    </li>
  );
}
