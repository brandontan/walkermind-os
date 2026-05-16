import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ── Tactical Terminal v3.2 palette ────────────────────────────────
        "bg-0":      "#02050B",
        "bg-1":      "#060A14",
        "bg-2":      "#0A0F1C",
        "surface":   "#0D1322",
        "surface-2": "#121A2D",
        "surface-3": "#1A2540",

        "border-1": "rgba(245,200,66,0.06)",
        "border-2": "rgba(245,200,66,0.14)",
        "border-3": "rgba(245,200,66,0.28)",

        "ink-1": "#F0F5FF",
        "ink-2": "#8FA3C4",
        "ink-3": "#455370",
        "ink-4": "#2A3550",

        "gold":   "#F5C842",
        "gold-2": "#FFE066",
        "gold-3": "#C99A1F",

        "grn":   "#00FF9C",
        "grn-2": "rgba(0,255,156,0.12)",
        "red":   "#FF2D55",
        "red-2": "rgba(255,45,85,0.12)",
        "blue":  "#4D9FFF",
        "blue-2":"rgba(77,159,255,0.12)",
        "cyan":  "#00E5FF",

        // ── Backward-compat aliases (legacy components) ───────────────────
        bg:      "#02050B",
        primary: "#F0F5FF",
        muted:   "#8FA3C4",
        card:    "#0D1322",
        border:  "rgba(245,200,66,0.14)",
        green:   "#00FF9C",
        amber:   "#F5C842",
        yellow:  "#F5C842",
      },
      fontFamily: {
        display: ["Anton", "sans-serif"],          // hero numerals / titles
        hud:     ["Orbitron", "monospace"],        // labels / buttons
        sans:    ["Rajdhani", "sans-serif"],       // body
        mono:    ["JetBrains Mono", "monospace"],  // data / addresses
      },
      maxWidth: {
        mobile: "440px",
      },
      borderRadius: {
        card:   "0px",
        button: "0px",
      },
      keyframes: {
        pulse: {
          "0%,100%": { opacity: "1" },
          "50%":     { opacity: "0.4" },
        },
        revealUp: {
          from: { opacity: "0", transform: "translateY(8px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        contentIn: {
          from: { opacity: "0", transform: "translateY(8px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "status-pulse": "pulse 1.6s ease-in-out infinite",
        "page-in":      "contentIn 0.4s cubic-bezier(0.22,1,0.36,1) both",
      },
    },
  },
  plugins: [],
};

export default config;
