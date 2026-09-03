import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  [
    "inline-flex items-center justify-center whitespace-nowrap rounded-md",
    "font-sans text-sm font-semibold",
    "border-2 border-ink select-none",
    "transition-all duration-150 ease-out",
    "dark:border dark:border-border dark:rounded-lg dark:font-medium",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan focus-visible:ring-offset-2 focus-visible:ring-offset-background",
    "disabled:pointer-events-none disabled:opacity-50",
  ].join(" "),
  {
    variants: {
      variant: {
        default:
          "bg-blue text-white shadow-hard-blue hover:-translate-y-0.5 hover:shadow-hard-lg active:translate-y-0.5 active:shadow-hard-none dark:shadow-sm dark:hover:bg-blue-deep dark:active:scale-[0.98] dark:hover:translate-y-0",
        outline:
          "bg-cream text-ink shadow-hard-sm hover:-translate-y-0.5 hover:shadow-hard active:translate-y-0.5 active:shadow-hard-none dark:bg-card dark:text-foreground dark:border-border dark:shadow-sm dark:hover:bg-beige-deep dark:active:scale-[0.98] dark:hover:translate-y-0",
        destructive:
          "bg-destructive text-destructive-foreground shadow-hard-sm hover:-translate-y-0.5 hover:shadow-hard active:translate-y-0.5 active:shadow-hard-none dark:shadow-sm dark:hover:bg-destructive/90 dark:active:scale-[0.98] dark:hover:translate-y-0",
        secondary:
          "bg-beige-deep text-ink shadow-hard-sm hover:-translate-y-0.5 hover:shadow-hard active:translate-y-0.5 active:shadow-hard-none dark:bg-beige-deep dark:text-foreground dark:border-border dark:shadow-sm dark:hover:bg-border dark:active:scale-[0.98] dark:hover:translate-y-0",
        ghost:
          "border-transparent bg-transparent text-foreground hover:bg-accent hover:text-accent-foreground hover:shadow-none dark:hover:bg-beige-deep",
        link: "border-transparent bg-transparent text-blue underline underline-offset-4 hover:text-blue/80",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-md px-3",
        lg: "h-11 rounded-md px-8 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button };
export default Button;
