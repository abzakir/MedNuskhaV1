"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { api, type Me, type WhatsAppStatus } from "@/lib/api";
import { authConfigured, getSession, signOut } from "@/lib/supabase";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [wa, setWa] = useState<WhatsAppStatus | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let alive = true;

    (async () => {
      // With auth configured, a missing session means straight to /login.
      // Without it, the backend's dev bypass is in play and we carry on.
      if (authConfigured) {
        const session = await getSession();
        if (!session) {
          router.replace("/login");
          return;
        }
      }
      try {
        const profile = await api.me();
        if (alive) setMe(profile);
      } catch {
        if (alive && authConfigured) router.replace("/login");
      } finally {
        if (alive) setChecked(true);
      }
    })();

    return () => {
      alive = false;
    };
  }, [router]);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      api
        .whatsappStatus()
        .then((s) => alive && setWa(s))
        .catch(() => alive && setWa({ state: "unreachable" }));
    tick();
    const id = setInterval(tick, 20_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  if (!checked) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  const connected = wa?.state === "connected";

  return (
    <div className="min-h-screen bg-paper">
      <header className="sticky top-0 z-10 border-b bg-background/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-5xl items-center gap-5 px-4">
          <Link
            href="/dashboard"
            className="font-display text-2xl leading-none tracking-tight text-primary transition-opacity hover:opacity-80"
          >
            MedNuskha
          </Link>

          <nav className="hidden gap-5 sm:flex">
            <NavLink href="/dashboard" active={pathname === "/dashboard"}>
              Patients
            </NavLink>
            <NavLink
              href="/dashboard/profile"
              active={pathname === "/dashboard/profile"}
            >
              My details
            </NavLink>
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <span
              className="flex items-center gap-1.5 text-xs text-muted-foreground"
              title={
                connected
                  ? `WhatsApp connected as ${wa?.me ?? "unknown"}`
                  : "Reminders cannot be sent right now"
              }
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  connected ? "bg-taken animate-breathe" : "bg-missed"
                }`}
              />
              <span className="hidden sm:inline">
                WhatsApp {connected ? "connected" : (wa?.state ?? "…")}
              </span>
            </span>

            {me && (
              <span className="hidden text-sm text-muted-foreground md:inline">
                {me.name}
              </span>
            )}

            <Button
              variant="ghost"
              size="sm"
              onClick={async () => {
                await signOut();
                router.replace("/login");
              }}
            >
              Sign out
            </Button>
          </div>
        </div>
      </header>

      {!connected && (
        <div className="border-b border-late/30 bg-late-soft">
          <div className="mx-auto max-w-5xl px-4 py-2 text-sm text-late">
            <strong className="font-medium">Reminders are not being delivered.</strong>{" "}
            {wa?.state === "qr"
              ? "The WhatsApp bridge is waiting for a QR scan."
              : wa?.state === "unreachable"
                ? "The WhatsApp bridge isn't running — start it with ./bridge.ps1"
                : `Bridge state: ${wa?.state ?? "unknown"}.`}
          </div>
        </div>
      )}

      {me?.needs_phone && (
        <div className="border-b border-live/30 bg-live-soft">
          <div className="mx-auto max-w-5xl px-4 py-2 text-sm text-live">
            Add your own WhatsApp number so we can alert you when a dose is missed.{" "}
            <Link href="/dashboard/profile" className="font-medium underline underline-offset-2">
              Add it now
            </Link>
          </div>
        </div>
      )}

      <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
    </div>
  );
}

function NavLink({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`relative px-1 py-1.5 text-sm transition-colors ${
        active
          ? "font-medium text-foreground after:absolute after:inset-x-0 after:-bottom-px "
            + "after:h-0.5 after:rounded-full after:bg-primary after:content-['']"
          : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </Link>
  );
}
