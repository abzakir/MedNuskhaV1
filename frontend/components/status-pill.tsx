import { DOSE_LABELS, type DoseState } from "@/lib/api";
import { cn } from "@/lib/utils";

const TONES: Record<string, string> = {
  good: "bg-emerald-100 text-emerald-800 ring-emerald-600/20 dark:bg-emerald-950 dark:text-emerald-300 dark:ring-emerald-400/20",
  "good-muted":
    "bg-teal-100 text-teal-800 ring-teal-600/20 dark:bg-teal-950 dark:text-teal-300 dark:ring-teal-400/20",
  bad: "bg-rose-100 text-rose-800 ring-rose-600/20 dark:bg-rose-950 dark:text-rose-300 dark:ring-rose-400/20",
  warn: "bg-amber-100 text-amber-900 ring-amber-600/20 dark:bg-amber-950 dark:text-amber-300 dark:ring-amber-400/20",
  info: "bg-sky-100 text-sky-800 ring-sky-600/20 dark:bg-sky-950 dark:text-sky-300 dark:ring-sky-400/20",
  muted:
    "bg-slate-100 text-slate-700 ring-slate-500/20 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-400/20",
};

export function StatusPill({ state }: { state: DoseState }) {
  const meta = DOSE_LABELS[state] ?? { label: state, tone: "muted" };
  const live = state === "SENT" || state === "AWAITING_REPLY" || state === "REMINDED_AGAIN";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1",
        "text-xs font-medium ring-1 ring-inset",
        TONES[meta.tone],
      )}
    >
      {live && (
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      )}
      {meta.label}
    </span>
  );
}

/** Big adherence number. Null means nothing has been decided yet. */
export function AdherenceNumber({
  percent,
  size = "md",
}: {
  percent: number | null;
  size?: "sm" | "md" | "lg";
}) {
  const sizes = { sm: "text-xl", md: "text-3xl", lg: "text-5xl" };
  if (percent === null) {
    return (
      <span className={cn(sizes[size], "font-semibold text-muted-foreground")}>
        &mdash;
      </span>
    );
  }
  const tone =
    percent >= 85
      ? "text-emerald-600 dark:text-emerald-400"
      : percent >= 60
        ? "text-amber-600 dark:text-amber-400"
        : "text-rose-600 dark:text-rose-400";
  return (
    <span className={cn(sizes[size], "font-semibold tabular-nums", tone)}>
      {percent}
      <span className="text-[0.5em] font-medium">%</span>
    </span>
  );
}
