import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0E0E12",
        card: "#16161C",
        border: "#2A2A35",
        primary: "#F0F0F5",
        muted: "#6B6B80",
        amber: "#F5A623",
        green: "#22C55E",
        yellow: "#EAB308",
        red: "#EF4444",
      },
      fontFamily: {
        sans: ["Inter", "sans-serif"],
      },
      maxWidth: {
        mobile: "430px",
      },
    },
  },
  plugins: [],
};

export default config;
