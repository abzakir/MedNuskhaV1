"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { authConfigured, getSession } from "@/lib/supabase";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    (async () => {
      if (!authConfigured) {
        // No Supabase configured - the backend's dev bypass is in play.
        router.replace("/dashboard");
        return;
      }
      const session = await getSession();
      router.replace(session ? "/dashboard" : "/login");
    })();
  }, [router]);

  return (
    <main className="flex min-h-screen items-center justify-center">
      <p className="text-sm text-muted-foreground">MedNuskha…</p>
    </main>
  );
}
