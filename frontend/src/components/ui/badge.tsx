import { cn } from "@/lib/utils";

type StickerVariant = "blue" | "cyan" | "beige" | "ink" | "destructive" | "muted" | "verified" | "reworded" | "gap" | "alert";

const variantClasses: Record<StickerVariant, string> = {
  blue:       "bg-blue text-white border-blue-deep/30",
  cyan:       "bg-cyan text-white border-cyan-pale/30",
  beige:      "bg-beige-deep text-ink border-border",
  ink:        "bg-ink text-background border-ink",
  destructive:"bg-destructive text-white border-destructive/30",
  muted:      "bg-beige-deep text-ink-soft border-border",
  verified:   "bg-cyan text-white border-cyan/40",
  reworded:   "bg-blue text-white border-blue/40",
  gap:        "bg-destructive text-white border-destructive/40",
  alert:      "bg-amber-600 text-white border-amber-700/40",
};

export function Sticker({
  variant = "beige",
  rotate,
  className,
  children,
}: {
  variant?: StickerVariant;
  rotate?: -2 | 2;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "sticker",
        variantClasses[variant],
        className,
      )}
      style={rotate != null ? { transform: `rotate(${rotate}deg)` } : undefined}
    >
      {children}
    </span>
  );
}
