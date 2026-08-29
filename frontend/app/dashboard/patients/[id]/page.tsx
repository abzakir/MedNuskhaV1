"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { MedicineCard } from "@/components/medicine-card";
import { DoseChart } from "@/components/dose-chart";
import { PatientContact } from "@/components/patient-contact";
import { StatusPill, AdherenceNumber } from "@/components/status-pill";
import {
  api,
  type Dose,
  type EventRow,
  type History,
  type PatientDetail,
  type Today,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const SETTLED = ["TAKEN", "TAKEN_LATE", "MISSED", "SKIPPED"];
const URDU = /[؀-ۿ]/;

export default function PatientPage() {
  const { id } = useParams<{ id: string }>();
  const [patient, setPatient] = useState<PatientDetail | null>(null);
  const [today, setToday] = useState<Today | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [optinSent, setOptinSent] = useState(false);
  const [resuming, setResuming] = useState(false);

  // Which doses changed state on the last poll. This is the moment the whole
  // demo turns on - the patient replies on WhatsApp and this page catches up
  // within five seconds - so the row that changed says so rather than the
  // change happening silently between two identical-looking frames.
  const previous = useRef<Record<string, string>>({});
  const [justChanged, setJustChanged] = useState<Set<string>>(new Set());

  const loadPatient = useCallback(
    () => api.patient(id).then(setPatient).catch((e) => setError((e as Error).message)),
    [id],
  );

  useEffect(() => {
    loadPatient();
  }, [loadPatient]);

  useEffect(() => {
    let alive = true;

    const tick = () => {
      api
        .today(id)
        .then((t) => {
          if (!alive) return;
          const changed = new Set<string>();
          for (const dose of t.doses) {
            const before = previous.current[dose.id];
            if (before && before !== dose.state) changed.add(dose.id);
            previous.current[dose.id] = dose.state;
          }
          if (changed.size > 0) {
            setJustChanged(changed);
            setTimeout(() => {
              if (alive) setJustChanged(new Set());
            }, 2200);
          }
          setToday(t);
        })
        .catch(() => {});
      api.events(id).then((e) => alive && setEvents(e)).catch(() => {});
      api.history(id, 14).then((h) => alive && setHistory(h)).catch(() => {});
    };

    tick();
    const timer = setInterval(tick, 5_000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [id]);

  if (error) {
    return <p className="rounded-lg bg-missed-soft p-4 text-sm text-missed">{error}</p>;
  }
  if (!patient) {
    return <p className="text-sm text-muted-foreground">Loading&hellip;</p>;
  }

  const next = today?.doses.find((d) => !SETTLED.includes(d.state));

  return (
    <div className="space-y-10">
      {/* --------------------------------------------------------- header */}
      <header>
        <Link
          href="/dashboard"
          className="text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          &larr; All patients
        </Link>

        <div className="mt-4 flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <h1 className="font-display text-4xl leading-none tracking-tight">
              {patient.name}
            </h1>
            <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
              <span className="font-mono">+{patient.whatsapp_number}</span>
              <span aria-hidden className="text-border">
                &middot;
              </span>
              <span className={patient.opted_in ? "text-taken" : "text-late"}>
                {patient.opted_in ? "on WhatsApp" : "not opted in yet"}
              </span>
            </p>
            <div className="mt-2">
              <PatientContact patient={patient} onSaved={loadPatient} />
            </div>
          </div>

          <div className="flex items-center gap-2">
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
              {optinSent ? "Intro sent" : "Send intro message"}
            </Button>
            <Button asChild size="sm">
              <Link href={`/dashboard/patients/${id}/medicines/new`}>Add medicine</Link>
            </Button>
          </div>
        </div>
      </header>

      {patient.stopped && (
        <div className="rounded-lg border border-missed/40 bg-missed-soft p-4">
          <p className="text-sm text-missed">
            <strong className="font-semibold">
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

      {/* ----------------------------------------------- the answer, first */}
      <section className="grid gap-8 rounded-xl border bg-card p-6 shadow-card sm:grid-cols-[auto_1fr] sm:gap-10">
        <div>
          <Label>Adherence &middot; 14 days</Label>
          <div className="mt-2">
            <AdherenceNumber percent={patient.adherence.percent} size="lg" />
          </div>
          <p className="mt-3 max-w-[20ch] text-sm leading-snug text-muted-foreground">
            {sentence(patient, today)}
          </p>
        </div>

        <div className="min-w-0 self-end">
          <DoseChart doses={history?.doses ?? []} days={14} />
        </div>
      </section>

      {/* ---------------------------------------------------------- today */}
      <section>
        <SectionHead
          title="Today"
          aside={
            today ? (
              <span className="inline-flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
                <span className="h-1.5 w-1.5 animate-breathe rounded-full bg-taken" />
                live &middot; {today.server_time}
              </span>
            ) : null
          }
        />

        {!today || today.doses.length === 0 ? (
          <Empty>
            {patient.medicines.length === 0
              ? "No medicines yet. Add one and reminders start straight away."
              : "No doses due today."}
          </Empty>
        ) : (
          <ol className="ml-1 border-l border-border">
            {today.doses.map((dose) => (
              <DoseRow
                key={dose.id}
                dose={dose}
                isNext={next?.id === dose.id}
                flashing={justChanged.has(dose.id)}
              />
            ))}
          </ol>
        )}
      </section>

      {/* ------------------------------------------------------ medicines */}
      <section>
        <SectionHead title="Medicines" />
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
              <MedicineCard
                key={m.id}
                medicine={m}
                patientId={id}
                onChange={loadPatient}
              />
            ))}
          </div>
        )}
      </section>

      {/* ------------------------------------------------------- activity */}
      <section>
        <SectionHead title="Conversation" />
        <div className="overflow-hidden rounded-xl border bg-card">
          {events.length === 0 ? (
            <p className="p-8 text-center text-sm text-muted-foreground">Nothing yet.</p>
          ) : (
            <ul className="divide-y divide-border">
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

/* -------------------------------------------------------------------------- */

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[11px] font-medium uppercase tracking-label text-muted-foreground">
      {children}
    </span>
  );
}

function SectionHead({ title, aside }: { title: string; aside?: React.ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-4 border-b border-border pb-2">
      <h2 className="font-display text-xl leading-none">{title}</h2>
      {aside}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border bg-card p-8 text-center">
      <p className="text-sm text-muted-foreground">{children}</p>
    </div>
  );
}

/** One sentence answering the question the caretaker actually arrived with. */
function sentence(patient: PatientDetail, today: Today | null): string {
  if (patient.stopped) return "Reminders are stopped.";
  if (!today || today.doses.length === 0) return "Nothing due today.";

  const { taken, total, pending } = today.summary;
  if (pending === total) return `${total} due today, none answered yet.`;
  if (taken === total) return `All ${total} of today's doses taken.`;
  return `${taken} of ${total} taken today${pending ? `, ${pending} still to come` : ""}.`;
}

/** A dose as a stop on a time spine, rather than a cell in a table. */
function DoseRow({
  dose,
  isNext,
  flashing,
}: {
  dose: Dose;
  isNext: boolean;
  flashing: boolean;
}) {
  const said = dose.response_text ?? dose.reason;
  const isUrdu = said ? URDU.test(said) : false;

  return (
    <li
      className={cn(
        "group relative grid grid-cols-[3.5rem_1fr] items-baseline gap-x-3 rounded-r-lg py-3 pl-5 pr-4",
        "transition-colors duration-300",
        // The bead on the spine. Filled for the next dose due, hollow otherwise.
        "before:absolute before:left-[-4.5px] before:top-[1.35rem] before:h-2 before:w-2",
        "before:rounded-full before:border-2 before:border-card before:bg-border before:content-['']",
        isNext && "bg-accent/60 before:bg-live",
        flashing && "animate-settle bg-taken-soft",
        !isNext && !flashing && "hover:bg-muted/40",
      )}
    >
      <time className="font-mono text-sm font-medium tnum">{dose.time}</time>

      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-medium">{dose.medicine}</span>
          <StatusPill state={dose.state} />
          {dose.caretaker_alerted && (
            <span className="text-xs text-muted-foreground">you were alerted</span>
          )}
        </div>

        {said && (
          <p className={cn("text-sm text-muted-foreground", isUrdu ? "urdu" : "italic")}>
            &ldquo;{said}&rdquo;
            {dose.response_source === "voice" && (
              <span className="ml-1.5 not-italic" title="sent as a voice note">
                &#127908;
              </span>
            )}
          </p>
        )}
      </div>
    </li>
  );
}

function EventItem({ event }: { event: EventRow }) {
  const time = new Date(event.at).toLocaleString([], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
  const body = event.body ?? event.template ?? event.type ?? "";
  const isUrdu = URDU.test(body);

  if (event.kind === "symptom") {
    const urgent = event.severity === "emergency";
    return (
      <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
        <span className="w-24 shrink-0 font-mono text-xs text-muted-foreground">
          {time}
        </span>
        <span
          className={cn(
            "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-label",
            urgent ? "bg-missed-soft text-missed" : "bg-late-soft text-late",
          )}
        >
          {urgent ? "urgent" : "symptom"}
        </span>
        <span className={cn("min-w-0 flex-1", isUrdu ? "urdu" : "italic")}>
          &ldquo;{event.body}&rdquo;
        </span>
      </li>
    );
  }

  const inbound = event.direction === "in";
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
      <span className="w-24 shrink-0 font-mono text-xs text-muted-foreground">
        {time}
      </span>
      <span
        className={cn(
          "w-[4.5rem] shrink-0 text-[10px] font-semibold uppercase tracking-label",
          inbound ? "text-taken" : "text-muted-foreground",
        )}
      >
        {inbound ? "they said" : "we sent"}
      </span>
      <span
        className={cn(
          "min-w-0 flex-1 truncate",
          inbound ? "text-foreground" : "text-muted-foreground",
          isUrdu && "urdu",
        )}
      >
        {body}
      </span>
      {event.status === "failed" && (
        <span className="shrink-0 text-xs text-missed">failed</span>
      )}
    </li>
  );
}
