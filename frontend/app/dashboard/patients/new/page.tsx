"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";

const RELATIONS = [
  { value: "beta", label: "Son" },
  { value: "beti", label: "Daughter" },
  { value: "shohar", label: "Husband" },
  { value: "biwi", label: "Wife" },
  { value: "caregiver", label: "Other" },
];

export default function AddPatientPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [number, setNumber] = useState("");
  const [language, setLanguage] = useState("ur");
  const [relation, setRelation] = useState("beta");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api.addPatient({
        name,
        whatsapp_number: number,
        language,
        relation,
      });
      router.push(`/dashboard/patients/${created.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-lg">
      <Link
        href="/dashboard"
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        &larr; Back
      </Link>

      <h1 className="mt-4 text-2xl font-semibold tracking-tight">
        Who are you looking after?
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">
        They don&apos;t need to install anything. Reminders arrive on their WhatsApp.
      </p>

      <form onSubmit={submit} className="mt-8 space-y-5 rounded-xl border bg-card p-6">
        <div className="space-y-1.5">
          <Label htmlFor="name">Their name</Label>
          <Input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ammi"
            required
            autoFocus
          />
          <p className="text-xs text-muted-foreground">
            This is how the reminder will address them — use what they&apos;re called at home.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="number">Their WhatsApp number</Label>
          <Input
            id="number"
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            placeholder="0300 1234567"
            required
            inputMode="tel"
          />
          <p className="text-xs text-muted-foreground">
            Any format works — 0300…, +92 300…, or 92300…
          </p>
        </div>

        <div className="space-y-1.5">
          <Label>You are their…</Label>
          <div className="flex flex-wrap gap-2">
            {RELATIONS.map((r) => (
              <button
                key={r.value}
                type="button"
                onClick={() => setRelation(r.value)}
                className={`rounded-full border px-3.5 py-1.5 text-sm transition-colors ${
                  relation === r.value
                    ? "border-teal-600 bg-teal-50 text-teal-800 dark:bg-teal-950 dark:text-teal-300"
                    : "hover:bg-muted"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-1.5">
          <Label>Message language</Label>
          <div className="flex gap-2">
            {[
              { value: "ur", label: "Urdu (Roman)" },
              { value: "en", label: "English" },
            ].map((l) => (
              <button
                key={l.value}
                type="button"
                onClick={() => setLanguage(l.value)}
                className={`rounded-full border px-3.5 py-1.5 text-sm transition-colors ${
                  language === l.value
                    ? "border-teal-600 bg-teal-50 text-teal-800 dark:bg-teal-950 dark:text-teal-300"
                    : "hover:bg-muted"
                }`}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-900 dark:bg-rose-950/50 dark:text-rose-200">
            {error}
          </p>
        )}

        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "Adding…" : "Add patient"}
        </Button>
      </form>
    </div>
  );
}
