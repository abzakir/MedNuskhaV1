"use client";

/**
 * Change the patient's name, WhatsApp number, or language.
 *
 * Until this existed, a mistyped number could only be fixed by deleting the
 * patient and starting again - throwing away every dose, every reply and both
 * reports. It is the most common real mistake in the product and it deserved
 * a repair rather than a restart.
 *
 * The number field carries a warning rather than hiding one. A new number is
 * a different handset belonging to somebody who has agreed to nothing, so the
 * server resets the opt-in and nothing is sent there until they answer the
 * intro message. That is a surprising thing to have happen silently, so it is
 * said out loud before the caretaker presses save.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type PatientDetail } from "@/lib/api";
import { normalizeNumber } from "@/lib/utils";

export function PatientContact({
  patient,
  onSaved,
}: {
  patient: PatientDetail;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(patient.name);
  const [number, setNumber] = useState(patient.whatsapp_number);
  const [language, setLanguage] = useState(patient.language);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const numberChanged =
    normalizeNumber(number) !== normalizeNumber(patient.whatsapp_number);
  const nothingChanged =
    name.trim() === patient.name && !numberChanged && language === patient.language;

  function start() {
    setName(patient.name);
    setNumber(patient.whatsapp_number);
    setLanguage(patient.language);
    setError(null);
    setOpen(true);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.updatePatient(patient.id, {
        name: name.trim(),
        whatsapp_number: normalizeNumber(number),
        language,
      });
      setOpen(false);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={start}
        className="text-xs text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
      >
        Change number or name
      </button>
    );
  }

  return (
    <form
      onSubmit={save}
      className="mt-4 space-y-4 rounded-lg border bg-card p-4 shadow-card"
    >
      <div className="space-y-1.5">
        <Label htmlFor="p-name">Name</Label>
        <Input
          id="p-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={80}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="p-number">WhatsApp number</Label>
        <Input
          id="p-number"
          value={number}
          onChange={(e) => setNumber(e.target.value)}
          inputMode="tel"
          placeholder="923001234567"
          required
          className="font-mono"
        />
        <p className="text-xs text-muted-foreground">
          Country code, no + and no leading zero.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="p-language">Language</Label>
        <select
          id="p-language"
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          className="flex h-10 w-full rounded-md border border-input bg-card px-3 py-2 text-sm
                     focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring
                     focus-visible:ring-offset-2"
        >
          <option value="ur">Roman Urdu</option>
          <option value="en">English</option>
        </select>
      </div>

      {numberChanged && (
        <p className="rounded-lg bg-late-soft p-3 text-xs leading-relaxed text-late">
          <strong className="font-semibold">
            A new number has to agree before we message it.
          </strong>{" "}
          Reminders stop until {name.trim() || "they"} replies to the intro
          message on the new phone. Everything already recorded is kept.
        </p>
      )}

      {error && (
        <p className="rounded-lg bg-missed-soft p-3 text-sm text-missed">{error}</p>
      )}

      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={busy || nothingChanged}>
          {busy ? "Saving…" : "Save changes"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setOpen(false)}
          disabled={busy}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}
