"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { AdherenceNumber } from "@/components/status-pill";
import { api, type PatientSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function OverviewPage() {
  const [patients, setPatients] = useState<PatientSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .patients()
        .then((p) => alive && setPatients(p))
        .catch((e) => alive && setError((e as Error).message));
    load();
    // The overview is a glance, not a live view - the patient page polls.
    const id = setInterval(load, 15_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  if (error) {
    return <p className="rounded-lg bg-missed-soft p-4 text-sm text-missed">{error}</p>;
  }
  if (patients === null) {
    return <p className="text-sm text-muted-foreground">Loading&hellip;</p>;
  }

  const needAttention = patients.filter((p) => p.today.missed > 0 || p.stopped);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl leading-none tracking-tight">
            Your family
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {patients.length === 0
              ? "Nobody added yet."
              : needAttention.length > 0
                ? `${needAttention.length} ${needAttention.length === 1 ? "person needs" : "people need"} a look today.`
                : `Everyone is keeping up.`}
          </p>
        </div>
        <Button asChild>
          <Link href="/dashboard/patients/new">Add someone</Link>
        </Button>
      </div>

      {patients.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {patients.map((p) => (
            <PatientCard key={p.id} patient={p} />
          ))}
        </div>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-xl border border-dashed bg-card p-12 text-center">
      <h2 className="font-display text-2xl">Start with one person</h2>
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted-foreground">
        Add the family member you look after, then their medicines and times.
        They&apos;ll get a WhatsApp reminder at every dose &mdash; nothing to install,
        nothing to learn.
      </p>
      <Button asChild className="mt-6">
        <Link href="/dashboard/patients/new">Add your first patient</Link>
      </Button>
    </div>
  );
}

function PatientCard({ patient }: { patient: PatientSummary }) {
  const { today, adherence } = patient;
  const attention = today.missed > 0 || patient.stopped;

  return (
    <Link
      href={`/dashboard/patients/${patient.id}`}
      className={cn(
        "group block rounded-xl border bg-card p-5 shadow-card transition-all",
        "hover:-translate-y-0.5 hover:shadow-lift",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        // A left edge that carries the state, so a wall of cards is scannable
        // without reading any of them.
        attention ? "border-l-[3px] border-l-missed" : "border-l-[3px] border-l-taken",
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="truncate font-display text-2xl leading-tight transition-colors group-hover:text-primary">
            {patient.name}
          </h3>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            +{patient.whatsapp_number}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <AdherenceNumber percent={adherence.percent} />
          <p className="mt-1 text-[10px] uppercase tracking-label text-muted-foreground">
            {adherence.days} days
          </p>
        </div>
      </div>

      {patient.stopped && (
        <p className="mt-4 rounded-md bg-missed-soft px-3 py-2 text-xs text-missed">
          Replied STOP &mdash; reminders are paused.
        </p>
      )}

      {/* Today, as a single readable line rather than three anonymous numbers. */}
      <div className="mt-4 border-t border-border pt-4">
        {today.total === 0 ? (
          <p className="text-sm text-muted-foreground">
            {patient.medicine_count === 0
              ? "No medicines yet — add one to start reminders."
              : "Nothing due today."}
          </p>
        ) : (
          <>
            <TodayBar today={today} />
            <p className="mt-2.5 text-sm">
              <span className="font-medium">
                {today.taken} of {today.total}
              </span>{" "}
              <span className="text-muted-foreground">taken today</span>
              {today.missed > 0 && (
                <span className="text-missed"> &middot; {today.missed} missed</span>
              )}
              {today.pending > 0 && (
                <span className="text-muted-foreground">
                  {" "}
                  &middot; {today.pending} to come
                </span>
              )}
            </p>
          </>
        )}
      </div>
    </Link>
  );
}

/** Today's doses as one bar: kept, missed, still to come. */
function TodayBar({
  today,
}: {
  today: { total: number; taken: number; missed: number; pending: number };
}) {
  const segments = [
    { n: today.taken, className: "bg-taken", label: "taken" },
    { n: today.missed, className: "bg-missed", label: "missed" },
    { n: today.pending, className: "bg-pending-soft", label: "still to come" },
  ].filter((s) => s.n > 0);

  return (
    <div
      className="flex h-1.5 gap-px overflow-hidden rounded-full"
      role="img"
      aria-label={segments.map((s) => `${s.n} ${s.label}`).join(", ")}
    >
      {segments.map((s) => (
        <span
          key={s.label}
          className={cn("h-full transition-all duration-500", s.className)}
          style={{ flexGrow: s.n }}
        />
      ))}
    </div>
  );
}
