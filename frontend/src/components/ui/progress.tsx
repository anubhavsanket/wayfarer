import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { countUp, widthTo } from "@/lib/animations";

/**
 * Animated score bar with a number label.
 * Mounts at 0 and animates to `value`.
 */
export function ScoreBar({
  value,
  max = 100,
  decimals = 0,
  prefix = "",
  suffix = "",
  label,
  className,
}: {
  value: number;
  max?: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  label?: string;
  className?: string;
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const numRef = useRef<HTMLSpanElement>(null);
  const pct = Math.min(100, (value / max) * 100);

  // Pick a bar colour based on score
  const barColor =
    pct >= 70
      ? "bg-cyan"
      : pct >= 40
        ? "bg-blue"
        : "bg-destructive";

  useEffect(() => {
    if (barRef.current) widthTo(barRef.current, pct, 1000);
    if (numRef.current) {
      countUp(numRef.current, value, {
        decimals,
        prefix,
        suffix: suffix || "%",
        duration: 900,
      });
    }
  }, [pct, value, decimals, prefix, suffix]);

  return (
    <div className={cn("space-y-1.5", className)}>
      {label && (
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
      )}
      <div className="flex items-baseline gap-3">
        <span
          ref={numRef}
          className="font-display text-3xl font-bold tabular-nums leading-none"
        >
          {suffix ? `${value}${suffix}` : value}
        </span>
      </div>
      <div className="relative h-2.5 w-full overflow-hidden rounded-full border border-border bg-beige-deep">
        <div
          ref={barRef}
          className={cn("absolute inset-y-0 left-0 origin-left rounded-full", barColor)}
          style={{ transform: "scaleX(0)" }}
        />
      </div>
    </div>
  );
}
