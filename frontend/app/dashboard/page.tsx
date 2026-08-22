"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { AdherenceNumber } from "@/components/status-pill";
import { api, type PatientSummary } from "@/lib/api";

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
    return (
      <p className="rounded-lg bg-rose-50 p-4 text-sm text-rose-900 dark:bg-rose-950/50 dark:text-rose-200">
        {error}
      </p>
    );
  }

  if (patients === null) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Your family</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {patients.length === 0
              ? "Nobody added yet."
              : `${patients.length} ${patients.length === 1 ? "person" : "people"} under your care.`}
          </p>
        </div>
        <Button asChild>
          <Link href="/dashboard/patients/new">Add someone</Link>
        </Button>
      </div>

      {patients.length === 0 ? <EmptyState /> : (
        <div className="grid gap-4 sm:grid-cols-2">
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
    <div className="rounded-xl border border-dashed bg-card p-10 text-center">
      <h2 className="text-lg font-medium">Start with one person</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
        Add the family member you look after, then their medicines and times.
        They&apos;ll get a WhatsApp reminder at every dose — nothing to install,
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
  const allDone = today.total > 0 && today.pending === 0 && today.missed === 0;

  return (
    <Link
      href={`/dashboard/patients/${patient.id}`}
      className="group rounded-xl border bg-card p-5 transition-shadow hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="truncate text-lg font-medium group-hover:text-teal-700 dark:group-hover:text-teal-400">
            {patient.name}
          </h3>
          <p className="mt-0.5 font-mono text-xs text-muted-foreground">
            +{patient.whatsapp_number}
          </p>
        </div>
        <div className="text-right">
          <AdherenceNumber percent={adherence.percent} />
          <p className="text-[11px] text-muted-foreground">
            last {adherence.days} days
          </p>
        </div>
      </div>

      {patient.stopped && (
        <p className="mt-3 rounded-md bg-rose-50 px-2.5 py-1.5 text-xs text-rose-900 dark:bg-rose-950/50 dark:text-rose-200">
          This patient replied STOP — reminders are paused.
        </p>
      )}

      <dl className="mt-4 grid grid-cols-3 gap-2 border-t pt-4 text-center">
        <Stat label="Today" value={today.total} />
        <Stat label="Taken" value={today.taken} tone={today.taken > 0 ? "good" : undefined} />
        <Stat
          label={today.missed > 0 ? "Missed" : "Pending"}
          value={today.missed > 0 ? today.missed : today.pending}
          tone={today.missed > 0 ? "bad" : undefined}
        />
      </dl>

      <p className="mt-3 text-xs text-muted-foreground">
        {patient.medicine_count === 0
          ? "No medicines yet — add one to start reminders."
          : allDone
            ? `All ${today.total} doses done today.`
            : `${patient.medicine_count} ${patient.medicine_count === 1 ? "medicine" : "medicines"}`}
      </p>
    </Link>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "good" | "bad";
}) {
  const colour =
    tone === "good"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "bad"
        ? "text-rose-600 dark:text-rose-400"
        : "";
  return (
    <div>
      <dd className={`text-xl font-semibold tabular-nums ${colour}`}>{value}</dd>
      <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
    </div>
  );
}
