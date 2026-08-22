"use client";

/**
 * Add a medicine.
 *
 * The AI drafts what the medicine is for; the caretaker reads it, corrects
 * anything wrong, and confirms. Nothing is saved and nothing reaches the
 * patient until they press Confirm — that is invariant 3, and it is the one
 * place in this product where a plausible-sounding hallucination would become
 * a patient-safety problem rather than a bug.
 */

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type MedicineDraft } from "@/lib/api";

const TENURES = [7, 14, 30];
const COMMON_TIMES = ["08:00", "13:00", "20:00", "22:00"];

export default function AddMedicinePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [step, setStep] = useState<1 | 2>(1);
  const [name, setName] = useState("");
  const [strength, setStrength] = useState("");
  const [draft, setDraft] = useState<MedicineDraft | null>(null);
  const [pristine, setPristine] = useState<MedicineDraft | null>(null);

  const [purposeUr, setPurposeUr] = useState("");
  const [purposeEn, setPurposeEn] = useState("");
  const [foodRule, setFoodRule] = useState("");

  const [times, setTimes] = useState<string[]>(["08:00"]);
  const [days, setDays] = useState(7);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function lookup(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const d = await api.lookupMedicine(name);
      setDraft(d);
      setPristine(d);
      setPurposeUr(d.purpose_ur ?? "");
      setPurposeEn(d.purpose_en ?? "");
      setFoodRule(d.food_rule ?? "");
      setStep(2);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const edited =
    !!pristine &&
    (purposeUr !== (pristine.purpose_ur ?? "") ||
      purposeEn !== (pristine.purpose_en ?? "") ||
      foodRule !== (pristine.food_rule ?? ""));

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    if (times.length === 0) {
      setError("Pick at least one time of day.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.addMedicine({
        patient_id: id,
        name,
        strength: strength || undefined,
        dose_times: times,
        duration_days: days,
        purpose_ur: purposeUr || undefined,
        purpose_en: purposeEn || undefined,
        food_rule: foodRule || undefined,
        edited,
      });
      router.push(`/dashboard/patients/${id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  function toggleTime(t: string) {
    setTimes((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t].sort(),
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <Link
        href={`/dashboard/patients/${id}`}
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        &larr; Back to patient
      </Link>

      <h1 className="mt-4 text-2xl font-semibold tracking-tight">Add a medicine</h1>

      <ol className="mt-6 flex items-center gap-2 text-sm">
        <Step n={1} active={step === 1} done={step > 1} label="Name it" />
        <span className="h-px w-8 bg-border" />
        <Step n={2} active={step === 2} done={false} label="Check & confirm" />
      </ol>

      {/* ---------------------------------------------- step 1 */}
      {step === 1 && (
        <form onSubmit={lookup} className="mt-6 space-y-5 rounded-xl border bg-card p-6">
          <div className="space-y-1.5">
            <Label htmlFor="med">Medicine name</Label>
            <Input
              id="med"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Panadol"
              required
              autoFocus
            />
            <p className="text-xs text-muted-foreground">
              As written on the prescription or the box.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="strength">Strength (optional)</Label>
            <Input
              id="strength"
              value={strength}
              onChange={(e) => setStrength(e.target.value)}
              placeholder="500mg"
            />
            <p className="text-xs text-muted-foreground">
              Included in every reminder, so they know exactly which one to take.
            </p>
          </div>

          {error && <ErrorBox message={error} />}

          <Button type="submit" className="w-full" disabled={busy || !name.trim()}>
            {busy ? "Looking it up…" : "Look up"}
          </Button>
        </form>
      )}

      {/* ---------------------------------------------- step 2 */}
      {step === 2 && draft && (
        <form onSubmit={confirm} className="mt-6 space-y-6">
          <div className="rounded-xl border bg-card p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="font-medium">
                  What is {name} {strength} for?
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {draft.source === "existing"
                    ? "Someone has added this before — check it still fits your patient."
                    : draft.recognised === false
                      ? "The AI didn't recognise this one. Please write it yourself."
                      : "Drafted by AI. Read it carefully and correct anything wrong."}
                </p>
              </div>
              <span className="shrink-0 rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-300">
                Needs your OK
              </span>
            </div>

            <p className="mt-4 rounded-lg bg-muted/60 p-3 text-sm text-muted-foreground">
              Your family member will never be told any of this until you confirm it.
              If you&apos;re unsure, leave it blank — the agent will simply say it
              doesn&apos;t know rather than guess.
            </p>

            <div className="mt-5 space-y-4">
              <Field
                id="p-ur"
                label="Purpose (Roman Urdu)"
                value={purposeUr}
                onChange={setPurposeUr}
                placeholder="bukhar aur dard ke liye"
              />
              <Field
                id="p-en"
                label="Purpose (English)"
                value={purposeEn}
                onChange={setPurposeEn}
                placeholder="for fever and pain"
              />
              <Field
                id="food"
                label="Food rule"
                value={foodRule}
                onChange={setFoodRule}
                placeholder="Khane ke baad lein."
              />
            </div>

            {edited && (
              <p className="mt-3 text-xs text-teal-700 dark:text-teal-400">
                You&apos;ve edited the draft — your wording will be saved, not the AI&apos;s.
              </p>
            )}
          </div>

          {/* times */}
          <div className="rounded-xl border bg-card p-6">
            <h2 className="font-medium">When should they take it?</h2>
            <div className="mt-4 flex flex-wrap gap-2">
              {COMMON_TIMES.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => toggleTime(t)}
                  className={`rounded-full border px-4 py-2 font-mono text-sm transition-colors ${
                    times.includes(t)
                      ? "border-teal-600 bg-teal-50 text-teal-800 dark:bg-teal-950 dark:text-teal-300"
                      : "hover:bg-muted"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>

            <div className="mt-4 flex items-end gap-2">
              <div className="space-y-1.5">
                <Label htmlFor="custom" className="text-xs">
                  Another time
                </Label>
                <Input
                  id="custom"
                  type="time"
                  className="w-36"
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v && !times.includes(v)) setTimes([...times, v].sort());
                  }}
                />
              </div>
            </div>

            {times.length > 0 && (
              <p className="mt-4 text-sm">
                <span className="text-muted-foreground">Reminders at </span>
                <span className="font-mono font-medium">{times.join(", ")}</span>
                <span className="text-muted-foreground">
                  {" "}
                  — {times.length}× a day
                </span>
              </p>
            )}
          </div>

          {/* tenure */}
          <div className="rounded-xl border bg-card p-6">
            <h2 className="font-medium">For how long?</h2>
            <div className="mt-4 flex flex-wrap gap-2">
              {TENURES.map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDays(d)}
                  className={`rounded-full border px-4 py-2 text-sm transition-colors ${
                    days === d
                      ? "border-teal-600 bg-teal-50 text-teal-800 dark:bg-teal-950 dark:text-teal-300"
                      : "hover:bg-muted"
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
                className="w-28"
              />
            </div>
            <p className="mt-3 text-sm text-muted-foreground">
              {days} days × {times.length || 0} a day ={" "}
              <strong className="text-foreground">{days * (times.length || 0)} doses</strong>.
              When the course ends, both reports are generated automatically.
            </p>
          </div>

          {error && <ErrorBox message={error} />}

          <div className="flex gap-3">
            <Button
              type="button"
              variant="outline"
              onClick={() => setStep(1)}
              disabled={busy}
            >
              Back
            </Button>
            <Button type="submit" className="flex-1" disabled={busy}>
              {busy ? "Saving…" : "Confirm & add"}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

function Step({
  n,
  active,
  done,
  label,
}: {
  n: number;
  active: boolean;
  done: boolean;
  label: string;
}) {
  return (
    <li className="flex items-center gap-2">
      <span
        className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium ${
          done
            ? "bg-teal-600 text-white"
            : active
              ? "bg-foreground text-background"
              : "bg-muted text-muted-foreground"
        }`}
      >
        {done ? "✓" : n}
      </span>
      <span className={active || done ? "font-medium" : "text-muted-foreground"}>
        {label}
      </span>
    </li>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}

function ErrorBox({ message }: { message: string }) {
  return (
    <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-900 dark:bg-rose-950/50 dark:text-rose-200">
      {message}
    </p>
  );
}
