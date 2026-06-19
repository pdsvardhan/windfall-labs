"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Cockpit", icon: "▦" },
  { href: "/strategies/new", label: "New Strategy", icon: "✎" },
  { href: "/signals", label: "Live Signals", icon: "◎" },
  { href: "/paper", label: "Paper Trades", icon: "▤" },
  { href: "/walk-forward", label: "Walk-Forward", icon: "⇄" },
  { href: "/data", label: "Data Status", icon: "⛁" },
];

export function Nav() {
  const path = usePathname();
  return (
    <aside className="w-56 shrink-0 border-r border-border bg-card/40 px-3 py-5 flex flex-col">
      <div className="px-2 mb-6">
        <div className="text-lg font-semibold tracking-tight">Windfall Labs</div>
        <div className="text-xs text-muted mono">quant cockpit · NSE</div>
      </div>
      <nav className="flex flex-col gap-1">
        {LINKS.map((l) => {
          const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
          return (
            <Link
              key={l.href}
              href={l.href}
              className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${
                active ? "bg-accent/20 text-fg" : "text-muted hover:bg-white/5 hover:text-fg"
              }`}
            >
              <span className="w-4 text-center opacity-70">{l.icon}</span>
              {l.label}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto px-2 pt-4 text-[11px] text-muted mono leading-relaxed">
        signals-only · no execution
        <br />
        human places every order
      </div>
    </aside>
  );
}
