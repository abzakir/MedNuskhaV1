"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type Me } from "@/lib/api";

export default function ProfilePage() {
  const [me, setMe] = useState<Me | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.me().then((m) => {
      setMe(m);
      setName(m.name);
      setPhone(m.phone ?? "");
    });
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await api.updateMe({ name, phone });
      setMe(updated);
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!me) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="mx-auto max-w-lg">
      <Link href="/dashboard" className="text-sm text-muted-foreground hover:text-foreground">
        &larr; Back
      </Link>
      <h1 className="mt-4 text-2xl font-semibold tracking-tight">Your details</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        We alert you here when a dose is missed.
      </p>

      <form onSubmit={save} className="mt-8 space-y-5 rounded-xl border bg-card p-6">
        <div className="space-y-1.5">
          <Label htmlFor="name">Your name</Label>
          <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required />
          <p className="text-xs text-muted-foreground">
            Used in messages to your family member — &ldquo;{name || "…"} ko bata diya hai&rdquo;.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="phone">Your WhatsApp number</Label>
          <Input
            id="phone"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="0300 1234567"
            inputMode="tel"
          />
          <p className="text-xs text-muted-foreground">
            Missed-dose alerts come to this number. Without it, nobody is told.
          </p>
        </div>

        {me.email && (
          <div className="space-y-1.5">
            <Label>Email</Label>
            <p className="text-sm text-muted-foreground">{me.email}</p>
          </div>
        )}

        {error && (
          <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-900 dark:bg-rose-950/50 dark:text-rose-200">
            {error}
          </p>
        )}
        {saved && (
          <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200">
            Saved.
          </p>
        )}

        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </Button>
      </form>
    </div>
  );
}
