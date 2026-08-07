import { useEffect, useRef, type ReactNode } from "react";
import { revealUp, staggerReveal } from "@/lib/animations";

/** Animates its children in on mount (fade + slide up). */
export function Reveal({
  children,
  className = "",
  delay = 0,
  y,
  stagger,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
  y?: number;
  stagger?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ref.current) {
      revealUp(ref.current, { delay, y, stagger });
    }
  }, [delay, y, stagger]);

  return (
    <div
      ref={ref}
      className={className}
      style={{ opacity: 0 }}
    >
      {children}
    </div>
  );
}

/** Staggers the reveal of its direct children on mount. */
export function Stagger({
  children,
  className = "",
  stagger = 60,
  y = 16,
  duration,
}: {
  children: ReactNode;
  className?: string;
  stagger?: number;
  y?: number;
  duration?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ref.current) {
      staggerReveal(ref.current, { stagger, y, duration });
    }
  }, [stagger, y, duration]);

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}
