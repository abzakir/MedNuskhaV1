"use client";

/**
 * Deleting a patient, and deleting your own account.
 *
 * Both are irreversible and both are one click away from things nobody wants
 * to lose, so the pattern is the same for each:
 *
 * 1. It stays closed. An open form inviting deletion is a form somebody
 *    eventually fills in by accident.
 * 2. It says exactly what disappears, counted, before anything is typed.
 * 3. The name has to be typed to enable the button. Not a checkbox - typing
 *    forces you to read whose history you are about to erase, which is the
 *    whole point.
 *
 * The number being released is stated rather than hidden. It is the practical
 * consequence people actually ask about afterwards: yes, you can add that
 * person again later on the same phone.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { signOut } from "@/lib/supabase";
import { cn } from "@/lib/utils";

function Shell({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-missed/40 bg-card p-5">
      <h2 className="text-sm font-semibold uppercase tracking-label text-missed">
        {title}
      </h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function ConfirmName({
  expected,
  value,
  onChange,
  label,
}: {
  expected: string;
  value: string;
  onChange: (v: string) => void;
  label: string;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor="confirm-name" className="text-sm">
        {label}{" "}
        <span className="font-medium text-foreground">{expected}</span>
      </label>
      <Input
        id="confirm-name"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={expected}
        autoComplete="off"
      />
    </div>
  );
}

/* -------------------------------------------------------------- patient -- */

export function DeletePatient({
  patientId,
  name,
  number,
  doseCount,
}: {
  patientId: string;
  name: string;
  number: string;
  doseCount: number;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.deletePatient(patientId, confirm.trim());
      router.replace("/dashboard");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <Shell title="Danger zone">
        <p className="text-sm text-muted-foreground">
          Deleting {name} removes their medicines, every dose and every reply.
          There is no undo.
        </p>
        <Button
          variant="outline"
          size="sm"
          className="mt-3 border-missed/50 text-missed hover:bg-missed-soft"
          onClick={() => {
            setConfirm("");
            setError(null);
            setOpen(true);
          }}
        >
          Delete {name}
        </Button>
      </Shell>
    );
  }

  return (
    <Shell title="Delete this patient">
      <ul className="mb-4 space-y-1 text-sm text-muted-foreground">
        <li>&bull; Their medicines and schedules</li>
        <li>
          &bull; {doseCount > 0 ? `All ${doseCount} recorded doses` : "Their dose history"}{" "}
          and everything they replied
        </li>
        <li>&bull; Any reports already generated</li>
        <li className="text-foreground">
          &bull; <span className="font-mono">+{number}</span> is released, so you
          can add them again later
        </li>
      </ul>

      <ConfirmName
        expected={name}
        value={confirm}
        onChange={setConfirm}
        label="To confirm, type"
      />

      {error && (
        <p className="mt-3 rounded-lg bg-missed-soft p-3 text-sm text-missed">
          {error}
        </p>
      )}

      <div className="mt-4 flex gap-2">
        <Button
          size="sm"
          onClick={remove}
          disabled={busy || confirm.trim() !== name}
          className={cn("bg-missed text-white hover:bg-missed/90")}
        >
          {busy ? "Deleting…" : "Delete permanently"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setOpen(false)}
          disabled={busy}
        >
          Cancel
        </Button>
      </div>
    </Shell>
  );
}

/* -------------------------------------------------------------- account -- */

export function DeleteAccount({
  name,
  patientNames,
}: {
  name: string;
  patientNames: string[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.deleteMe(confirm.trim());
      // The Supabase login outlives the data, so end the session explicitly.
      // Otherwise the browser holds a token for an account that is gone and
      // the next request quietly creates a fresh empty one.
      await signOut();
      router.replace("/login");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <Shell title="Danger zone">
        <p className="text-sm text-muted-foreground">
          Closing your account removes everyone you look after and everything
          recorded about them. There is no undo.
        </p>
        <Button
          variant="outline"
          size="sm"
          className="mt-3 border-missed/50 text-missed hover:bg-missed-soft"
          onClick={() => {
            setConfirm("");
            setError(null);
            setOpen(true);
          }}
        >
          Delete my account
        </Button>
      </Shell>
    );
  }

  return (
    <Shell title="Delete your account">
      <ul className="mb-4 space-y-1 text-sm text-muted-foreground">
        {patientNames.length > 0 ? (
          <li className="text-foreground">
            &bull; <span className="font-medium">{patientNames.join(", ")}</span>{" "}
            {patientNames.length === 1 ? "is" : "are"} deleted, with every dose
            and reply
          </li>
        ) : (
          <li>&bull; You are not looking after anyone right now</li>
        )}
        <li>&bull; Your details and your WhatsApp number are released</li>
        <li>&bull; Reminders stop immediately</li>
      </ul>

      <p className="mb-4 rounded-lg bg-late-soft p-3 text-xs leading-relaxed text-late">
        Your sign-in itself is kept by our identity provider and we cannot
        remove it from here. Signing in again with the same email gives you a
        new, empty account &mdash; it will not bring any of this back.
      </p>

      <ConfirmName
        expected={name}
        value={confirm}
        onChange={setConfirm}
        label="To confirm, type your name"
      />

      {error && (
        <p className="mt-3 rounded-lg bg-missed-soft p-3 text-sm text-missed">
          {error}
        </p>
      )}

      <div className="mt-4 flex gap-2">
        <Button
          size="sm"
          onClick={remove}
          disabled={busy || confirm.trim() !== name}
          className="bg-missed text-white hover:bg-missed/90"
        >
          {busy ? "Deleting…" : "Delete my account"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setOpen(false)}
          disabled={busy}
        >
          Cancel
        </Button>
      </div>
    </Shell>
  );
}
