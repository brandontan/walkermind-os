import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg:      "#080A0F",
        surface: "#0D1117",
        card:    "#131920",
        border:  "#1A2332",
        gold:    "#F5C842",
        green:   "#00D68F",
        red:     "#FF4D6A",
        blue:    "#4D9EFF",
        primary: "#F0F0F5",
        muted:   "#6B7280",
        // backward-compat aliases
        amber:   "#F5C842",
        yellow:  "#F5C842",
      },
      fontFamily: {
        sans: ["Syne", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      maxWidth: {
        mobile: "430px",
      },
      borderRadius: {
        card:   "16px",
        button: "10px",
      },
    },
  },
  plugins: [],
};

export default config;
