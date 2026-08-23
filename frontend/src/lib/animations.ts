import { animate, stagger, createTimeline } from "animejs";

type AnimationTarget = string | HTMLElement[] | HTMLElement | NodeList;

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function markVisible(targets: string | HTMLElement[] | HTMLElement | NodeList) {
  if (typeof targets === "string") return;
  const els = "length" in targets ? [...targets] : [targets];
  (els as HTMLElement[]).forEach((el) => el.style.setProperty("opacity", "1"));
}

/** Fade in + slide up. Falls back to visible with no animation. */
export function revealUp(
  targets: AnimationTarget,
  opts?: {
    y?: number;
    delay?: number;
    stagger?: number;
    duration?: number;
  },
) {
  if (prefersReducedMotion()) {
    markVisible(targets);
    return undefined;
  }
  return animate(targets as HTMLElement | HTMLElement[], {
    opacity: [0, 1],
    translateY: [opts?.y ?? 20, 0],
    duration: opts?.duration ?? 550,
    ease: "outExpo",
    delay: opts?.stagger != null ? stagger(opts.stagger) : (opts?.delay ?? 0),
  });
}

/** Quick pop-in with overshoot. */
export function popIn(
  targets: AnimationTarget,
  delay?: number,
) {
  if (prefersReducedMotion()) {
    markVisible(targets);
    return undefined;
  }
  return animate(targets as HTMLElement | HTMLElement[], {
    scale: [0.88, 1],
    opacity: [0, 1],
    duration: 420,
    ease: "outBack",
    delay: delay ?? 0,
  });
}

/**
 * Animate a number counting up inside an element.
 * Calls `onComplete` when done.
 */
export function countUp(
  el: HTMLElement,
  to: number,
  opts?: {
    duration?: number;
    decimals?: number;
    prefix?: string;
    suffix?: string;
    onComplete?: () => void;
  },
) {
  const d = opts?.decimals ?? 0;
  const pfx = opts?.prefix ?? "";
  const sfx = opts?.suffix ?? "";

  if (prefersReducedMotion()) {
    el.textContent = `${pfx}${to.toFixed(d)}${sfx}`;
    opts?.onComplete?.();
    return undefined;
  }

  const proxy = { v: 0 };
  return animate(proxy, {
    v: to,
    duration: opts?.duration ?? 800,
    ease: "outExpo",
    onUpdate() {
      el.textContent = `${pfx}${proxy.v.toFixed(d)}${sfx}`;
    },
    onComplete() {
      opts?.onComplete?.();
    },
  });
}

/** Animate a progress bar's width to a percentage via scaleX. */
export function widthTo(
  el: HTMLElement,
  pct: number,
  duration?: number,
) {
  if (prefersReducedMotion()) {
    el.style.transformOrigin = "left";
    el.style.transform = `scaleX(${Math.min(1, pct / 100)})`;
    return undefined;
  }
  el.style.transformOrigin = "left";
  return animate(el, {
    scaleX: [0, Math.min(1, pct / 100)],
    duration: duration ?? 900,
    ease: "outExpo",
    delay: 200,
  });
}

/** Stagger-reveal direct children of a container. */
export function staggerReveal(
  container: Element,
  opts?: { stagger?: number; y?: number; duration?: number },
) {
  const children = Array.from(container.children) as HTMLElement[];
  if (prefersReducedMotion()) {
    children.forEach((c) => c.style.setProperty("opacity", "1"));
    return undefined;
  }
  return animate(children, {
    opacity: [0, 1],
    translateY: [opts?.y ?? 16, 0],
    duration: opts?.duration ?? 500,
    ease: "outExpo",
    delay: stagger(opts?.stagger ?? 60),
  });
}

/** Create a timeline for complex sequences (LoadingIndicator). */
export { createTimeline };
