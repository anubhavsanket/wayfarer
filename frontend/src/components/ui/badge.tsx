import { cn } from "@/lib/utils";

type StickerVariant = "blue" | "cyan" | "beige" | "ink" | "destructive" | "muted" | "verified" | "reworded" | "gap" | "alert";

const variantClasses: Record<StickerVariant, string> = {
  blue:       "bg-blue text-white",
  cyan:       "bg-cyan text-white",
  beige:      "bg-beige-deep text-white",
  ink:        "bg-ink text-white",
  destructive:"bg-destructive text-white",
  muted:      "bg-muted text-white",
  verified:   "bg-blue text-white",
  reworded:   "bg-cyan text-white",
  gap:        "bg-destructive text-white",
  alert:      "bg-[#e81123] text-white",
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
