import type { Config } from "tailwindcss";

// Palette mirrors the Ottomate UI master plan (terminal-dark cockpit).
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0B0E14",
        card: "#11161F",
        border: "#1F2630",
        fg: "#E6EDF3",
        muted: "#8B949E",
        gain: "#2EA043",
        loss: "#F85149",
        accent: "#388BFD",
        warn: "#D29922",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
