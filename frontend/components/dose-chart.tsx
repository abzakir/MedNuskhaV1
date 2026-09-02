"use client";

import { useMemo } from "react";
import { type Dose, type DoseState } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The chart this software replaces is paper, taped to a fridge: days down one
 * side, dose times across the other, a mark in each box. This is that chart.
 *
 * It answers the only question the caretaker actually has - "is she keeping
 * up?" - before a single word is read, because a column of gaps is visible
 * from across a room in a way that "78% adherence" is not.
 *
 * Fed from the same `dose_event` rows as everything else. No derived state,
 * no second source of truth.
 */

const STATE_CELL: Record<DoseState, string> = {
  TAKEN: "bg-taken border-taken",
  TAKEN_LATE: "bg-late border-late",
  MISSED: "bg-missed border-missed",
  SKIPPED: "bg-missed-soft border-missed",
  SCHEDULED: "bg-transparent border-border",
  SENT: "bg-live-soft border-live",
  AWAITING_REPLY: "bg-live-soft border-live",
  REMINDED_AGAIN: "bg-live-soft border-live",
};

const STATE_WORD: Record<DoseState, string> = {
  TAKEN: "taken",
  TAKEN_LATE: "taken late",
  MISSED: "missed",
  SKIPPED: "declined",
  SCHEDULED: "not due yet",
  SENT: "asked",
  AWAITING_REPLY: "waiting for a reply",
  REMINDED_AGAIN: "reminded again",
};

export type ChartDose = Pick<Dose, "id" | "state" | "scheduled_at" | "time" | "medicine">;

/** One cell per dose, grouped into a column per day. */
export function DoseChart({
  doses,
  days = 14,
  className,
}: {
  doses: ChartDose[];
  days?: number;
  className?: string;
}) {
  const columns = useMemo(() => buildColumns(doses, days), [doses, days]);

  const settled = doses.filter((d) =>
    ["TAKEN", "TAKEN_LATE", "MISSED", "SKIPPED"].includes(d.state),
  );
  const kept = settled.filter((d) => d.state === "TAKEN" || d.state === "TAKEN_LATE");

  if (columns.length === 0) {
    return (
      <div className={cn("rounded-lg border border-dashed p-8 text-center", className)}>
        <p className="text-sm text-muted-foreground">
          Nothing yet. The chart fills in as doses come round.
        </p>
      </div>
    );
  }

  return (
    <figure className={cn("space-y-3", className)}>
      <div className="overflow-x-auto pb-1">
        <div className="flex min-w-max items-end gap-[3px]">
          {columns.map((col) => (
            <div key={col.key} className="flex flex-col items-center gap-[3px]">
              <div className="flex flex-col-reverse gap-[3px]">
                {col.doses.map((dose) => (
                  <span
                    key={dose.id}
                    title={`${dose.medicine} · ${dose.time} · ${STATE_WORD[dose.state]}`}
                    className={cn(
                      "h-3.5 w-3.5 rounded-[3px] border transition-colors duration-500",
                      STATE_CELL[dose.state],
                      col.isToday && "ring-1 ring-foreground/25 ring-offset-1 ring-offset-background",
                    )}
                  />
                ))}
              </div>
              <span
                className={cn(
                  "font-mono text-[9px] leading-none",
                  col.isToday ? "font-bold text-foreground" : "text-muted-foreground",
                )}
              >
                {col.label}
              </span>
            </div>
          ))}
        </div>
      </div>

      <figcaption className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">
          {kept.length} of {settled.length} doses kept
        </span>
        <Key className="bg-taken" label="taken" />
        <Key className="bg-late" label="late" />
        <Key className="bg-missed" label="missed" />
        <Key className="bg-live-soft border border-live" label="waiting" />
        <Key className="border border-border" label="not due" />
      </figcaption>
    </figure>
  );
}

function Key({ className, label }: { className: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("h-2.5 w-2.5 rounded-[2px]", className)} />
      {label}
    </span>
  );
}

type Column = { key: string; label: string; isToday: boolean; doses: ChartDose[] };

function buildColumns(doses: ChartDose[], days: number): Column[] {
  if (doses.length === 0) return [];

  const byDay = new Map<string, ChartDose[]>();
  for (const dose of doses) {
    const key = dose.scheduled_at.slice(0, 10);
    const bucket = byDay.get(key);
    if (bucket) bucket.push(dose);
    else byDay.set(key, [dose]);
  }

  // Karachi, not the browser. Every `scheduled_at` the API returns is already
  // in Asia/Karachi, so anchoring the walk to the viewer's own clock shifts
  // the whole window for a caretaker abroad — and an overseas child watching a
  // parent in Pakistan is the ordinary case, not the edge one. From London at
  // 21:00 it is already tomorrow in Karachi, and today's column vanished.
  const today = karachiNow();
  const todayKey = localKey(today);

  // Walk backwards from today so the chart always ends on the current day,
  // even when the course finished last week or has not started yet.
  const keys: string[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    keys.push(localKey(d));
  }

  return keys
    .map((key) => ({
      key,
      label: key.slice(8),
      isToday: key === todayKey,
      doses: (byDay.get(key) ?? []).sort((a, b) =>
        a.scheduled_at.localeCompare(b.scheduled_at),
      ),
    }))
    .filter((col) => col.doses.length > 0 || col.isToday);
}

/** Now, as a Date whose Y/M/D read as the current Asia/Karachi calendar day. */
function karachiNow(): Date {
  try {
    // en-CA formats as YYYY-MM-DD, which is exactly the key shape.
    const [y, m, d] = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Karachi",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    })
      .format(new Date())
      .split("-")
      .map(Number);
    return new Date(y, m - 1, d);
  } catch {
    // A browser without that time zone in its ICU data still gets a chart.
    return new Date();
  }
}

function localKey(d: Date): string {
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, "0"),
    String(d.getDate()).padStart(2, "0"),
  ].join("-");
}
