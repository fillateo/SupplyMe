import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "#f8fafc",
        surface: "#ffffff",
        raised: "#f1f5f9",
        line: "#e2e8f0",
        "line-bright": "#cbd5e1",
        ink: {
          DEFAULT: "#0f172a",
          light: "#334155",
          muted: "#64748b",
          faint: "#94a3b8",
        },
        muted: "#64748b",
        faint: "#94a3b8",
        brand: {
          50: "#f0fdf4",
          100: "#dcfce7",
          500: "#10b981",
          600: "#059669",
          700: "#047857",
        },
        accent: {
          blue: "#2563eb",
          "blue-light": "#eff6ff",
          amber: "#d97706",
          "amber-light": "#fef3c7",
          rose: "#e11d48",
          "rose-light": "#ffe4e6",
          emerald: "#10b981",
          "emerald-light": "#ecfdf5",
          purple: "#7c3aed",
          "purple-light": "#f5f3ff",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "-apple-system", "BlinkMacSystemFont", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgba(15, 23, 42, 0.04)",
        subtle: "0 1px 2px 0 rgba(0, 0, 0, 0.05)",
        card: "0 1px 3px 0 rgba(0, 0, 0, 0.06), 0 1px 2px -1px rgba(0, 0, 0, 0.04)",
        lift: "0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.03)",
        modal: "0 20px 25px -5px rgba(0, 0, 0, 0.08), 0 8px 10px -6px rgba(0, 0, 0, 0.04)",
      },
      keyframes: {
        "rise-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "drawer-in": {
          from: { transform: "translateX(100%)" },
          to: { transform: "translateX(0)" },
        },
      },
      animation: {
        "rise-in": "rise-in 200ms cubic-bezier(0.16, 1, 0.3, 1)",
        "drawer-in": "drawer-in 240ms cubic-bezier(0.16, 1, 0.3, 1)",
      },
    },
  },
  plugins: [],
};

export default config;


