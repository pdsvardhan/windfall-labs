import type { Metadata } from "next";
import { Plus_Jakarta_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Nav } from "@/components/Nav";

const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-jakarta",
});
const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Windfall Labs",
  description: "Quant research & execution cockpit for Indian equities",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${jakarta.variable} ${mono.variable}`}>
      <body>
        <div className="relative overflow-hidden min-h-screen">
          {/* floating pastel blobs */}
          <div className="pointer-events-none absolute -z-0" style={{ top: 90, right: "5%", width: 120, height: 120, background: "linear-gradient(140deg,#c4e05a,#aacb3e)", borderRadius: "42% 58% 60% 40%/45% 45% 55% 55%", boxShadow: "0 18px 40px rgba(170,203,62,.35)", animation: "wfFloat 9s ease-in-out infinite" }} />
          <div className="pointer-events-none absolute -z-0" style={{ bottom: 80, left: -30, width: 96, height: 96, background: "linear-gradient(140deg,#f7b9dd,#f48fc6)", borderRadius: "58% 42% 45% 55%/55% 50% 50% 45%", boxShadow: "0 16px 36px rgba(244,143,198,.35)", animation: "wfFloat 11s ease-in-out infinite .8s" }} />
          <div className="pointer-events-none absolute -z-0" style={{ top: "46%", right: -26, width: 78, height: 78, background: "linear-gradient(140deg,#c4b6f7,#9f86ee)", borderRadius: "50%", boxShadow: "0 14px 30px rgba(159,134,238,.35)", animation: "wfFloat 10s ease-in-out infinite .4s" }} />

          <div className="relative z-10 mx-auto px-5 sm:px-8 pb-20 pt-5" style={{ maxWidth: 1680 }}>
            <Nav />
            <main className="min-w-0">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
