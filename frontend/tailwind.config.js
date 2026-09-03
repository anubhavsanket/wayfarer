/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // Neo-brutalist palette (CSS-var driven so it flips in dark mode)
        beige: {
          DEFAULT: "var(--beige)",
          deep: "var(--beige-deep)",
        },
        cream: "var(--cream)",
        ink: {
          DEFAULT: "var(--ink)",
          soft: "var(--ink-soft)",
        },
        blue: {
          DEFAULT: "var(--blue)",
          deep: "var(--blue-deep)",
          pale: "var(--blue-pale)",
        },
        cyan: {
          DEFAULT: "var(--cyan)",
          pale: "var(--cyan-pale)",
        },
      },
      fontFamily: {
        display: ["Petrona", "'Space Grotesk'", "Georgia", "serif"],
        sans: ["Inter", "'Source Sans 3'", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "'Azeret Mono'", "ui-monospace", "monospace"],
      },
      boxShadow: {
        hard: "4px 4px 0 0 var(--shadow-ink)",
        "hard-sm": "3px 3px 0 0 var(--shadow-ink)",
        "hard-lg": "6px 6px 0 0 var(--shadow-ink)",
        "hard-blue": "4px 4px 0 0 var(--blue-deep)",
        "hard-cyan": "4px 4px 0 0 var(--cyan)",
        "hard-none": "0 0 0 0 transparent",
        "sm": "0 1px 2px 0 rgb(0 0 0 / 0.05)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
