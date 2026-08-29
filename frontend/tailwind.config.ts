import type { Config } from "tailwindcss";

/**
 * The palette comes from technical documents — certificates of analysis,
 * customs declarations — rather than from product UI. Cool paper, petrol ink.
 * Signal colours encode HOW a fact was obtained, never whether it is good news.
 */
export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#EEF1F4",
        surface: "#FFFFFF",
        ink: "#12181F",
        muted: "#5A6672",
        faint: "#8A97A3",
        rule: "#D3DAE1",
        petrol: { DEFAULT: "#0B5D5B", deep: "#083F3E", light: "#E3EFEE" },
        amber: { DEFAULT: "#B4690E", light: "#FBF0E0" },
        rose: { DEFAULT: "#A32B36", light: "#FAE9EA" },
        slate2: { DEFAULT: "#8A97A3", light: "#EDF0F3" },
      },
      fontFamily: {
        // Human intent.
        serif: ["var(--font-plex-serif)", "Georgia", "serif"],
        // Machine findings.
        sans: ["var(--font-plex-sans)", "system-ui", "sans-serif"],
        // Anything measured, quoted, or sourced.
        mono: ["var(--font-plex-mono)", "ui-monospace", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.04em" }],
      },
      boxShadow: {
        card: "0 1px 2px rgba(18,24,31,0.05), 0 0 0 1px rgba(18,24,31,0.06)",
        drawer: "-12px 0 32px rgba(18,24,31,0.12)",
      },
      keyframes: {
        "slide-in": {
          from: { opacity: "0", transform: "translateY(-4px)" },
          to: { opacity: "1", transform: "none" },
        },
        "drawer-in": {
          from: { transform: "translateX(100%)" },
          to: { transform: "none" },
        },
        breathe: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
      },
      animation: {
        "slide-in": "slide-in 240ms ease-out",
        "drawer-in": "drawer-in 220ms cubic-bezier(0.32,0.72,0,1)",
        breathe: "breathe 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
