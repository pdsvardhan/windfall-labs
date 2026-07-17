"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const LINKS = [
  { href: "/", label: "Cockpit" },
  { href: "/strategies", label: "Strategies" },
  { href: "/leaderboards", label: "Leaderboards" },
  { href: "/signals", label: "Signals" },
  { href: "/paper", label: "Paper" },
  { href: "/reference", label: "Reference" },
];

export function Nav() {
  const path = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const isActive = (href: string) =>
    href === "/" ? path === "/" : path.startsWith(href);

  // Close the mobile menu on route change.
  useEffect(() => {
    setOpen(false);
  }, [path]);

  // Close the mobile menu on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="relative flex items-center justify-between bg-ink rounded-xl2 px-4 py-3 pl-5 animate-rise mb-1">
      <div className="flex items-center gap-5">
        <Link href="/" className="text-white font-extrabold text-[19px] tracking-tight">
          windfall labs
        </Link>
        <div className="hidden md:flex gap-0.5">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className="wf-nav" data-active={isActive(l.href) ? "1" : "0"}>
              {l.label}
            </Link>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-2.5">
        <button className="hidden md:inline-flex btn btn-acc" onClick={() => router.push("/strategies/new")}>
          + New strategy
        </button>
        <button
          className="md:hidden inline-flex items-center justify-center h-10 w-10 rounded-[11px] text-white transition-all hover:bg-white/10"
          aria-label="Toggle navigation menu"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="4" y1="7" x2="20" y2="7" />
            <line x1="4" y1="12" x2="20" y2="12" />
            <line x1="4" y1="17" x2="20" y2="17" />
          </svg>
        </button>
      </div>
      {open && (
        <div className="md:hidden absolute left-0 right-0 top-full mt-1 z-50 flex flex-col gap-0.5 bg-ink rounded-xl2 p-2 shadow-xl">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="wf-nav"
              data-active={isActive(l.href) ? "1" : "0"}
              onClick={() => setOpen(false)}
            >
              {l.label}
            </Link>
          ))}
          <button
            className="btn btn-acc mt-1"
            onClick={() => {
              setOpen(false);
              router.push("/strategies/new");
            }}
          >
            + New strategy
          </button>
        </div>
      )}
    </div>
  );
}
