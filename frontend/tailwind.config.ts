import type { Config } from "tailwindcss";

// "Pastel Pop" cockpit — lavender canvas, ink type, pastel cards, lime accent. Mirrors the
// Windfall App design concept (Plus Jakarta Sans + JetBrains Mono).
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#ece9f6",
        bg2: "#e7edf6",
        ink: "#16151c",
        card: "#ffffff",
        muted: "#6b6979",
        faint: "#7a7689", // A-X-2: darkened from #9694a4 for >=4.5:1 contrast on white
        line: "#f0eef6",
        // pastel surfaces
        limeY: "#f5e049",
        lime: "#b9d24a",
        acc: "#c4e05a", // primary lime accent
        pink: "#f7b9dd",
        sky: "#a9c9f2",
        lilac: "#c4b6f7",
        grape: "#7c5cd6",
        orange: "#f4855f",
        // ink-on-pastel label tones
        onLime: "#5b6b1f",
        onPink: "#8c4a72",
        onSky: "#345a87",
        onYellow: "#7d7220",
        onGrape: "#ddd6f5",
        // semantic
        gain: "#1f7a4d",
        loss: "#e0518a",
        warn: "#b88a1a",
        // legacy aliases kept so any stray class still resolves
        fg: "#16151c",
        accent: "#c4e05a",
        border: "#e6e2f0",
      },
      fontFamily: {
        sans: ["var(--font-jakarta)", "Plus Jakarta Sans", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "JetBrains Mono", "ui-monospace", "monospace"],
      },
      borderRadius: { xl2: "22px", xl3: "26px" },
      keyframes: {
        wfRise: { from: { opacity: "0", transform: "translateY(18px)" }, to: { opacity: "1", transform: "none" } },
        wfPop: { from: { opacity: "0", transform: "scale(.92)" }, to: { opacity: "1", transform: "scale(1)" } },
        wfFade: { from: { opacity: "0" }, to: { opacity: "1" } },
        wfFloat: { "0%,100%": { transform: "translateY(0) rotate(0)" }, "50%": { transform: "translateY(-14px) rotate(4deg)" } },
        wfPulse: { "0%,100%": { opacity: ".55", transform: "scale(1)" }, "50%": { opacity: "1", transform: "scale(1.25)" } },
      },
      animation: {
        rise: "wfRise .5s both",
        pop: "wfPop .5s both",
        fade: "wfFade .6s both",
        float: "wfFloat 9s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
export default config;
