import { useEffect, useRef } from "react";
import { createTimeline } from "animejs";

/** Animated loading indicator — bouncing dots with a scanning accent line. */
export function LoadingIndicator({
  message = "Thinking",
}: {
  message?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const dots = container.querySelectorAll<HTMLElement>(".dot");
    const scan = container.querySelector<HTMLElement>(".scan");
    if (!dots.length) return;

    const tl = createTimeline({ loop: true });

    tl.add(dots, { y: -8, duration: 200, ease: "inOutQuad" }, 0);
    tl.add(dots, { y: 0, duration: 200, ease: "inOutQuad" }, 200);

    if (scan) {
      tl.add(
        scan,
        { x: ["0%", "100%"], opacity: [0.2, 0.9, 0.2], duration: 1200, ease: "inOutSine" },
        0,
      );
    }

    return () => {
      tl.cancel();
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="flex items-center gap-4 rounded-lg border-2 border-ink bg-card px-5 py-4 shadow-hard-sm"
    >
      <div className="flex gap-1.5">
        <span className="dot inline-block h-2.5 w-2.5 rounded-full bg-blue" />
        <span className="dot inline-block h-2.5 w-2.5 rounded-full bg-cyan" />
        <span className="dot inline-block h-2.5 w-2.5 rounded-full bg-ink" />
      </div>

      <span className="font-mono text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {message}...
      </span>

      <div className="ml-auto h-1.5 w-24 overflow-hidden rounded-full border border-ink/20">
        <div className="scan h-full w-1/3 rounded-full bg-cyan" />
      </div>
    </div>
  );
}
