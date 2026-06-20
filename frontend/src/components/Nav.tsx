"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Cockpit" },
  { href: "/strategies", label: "Strategies" },
  { href: "/signals", label: "Signals" },
  { href: "/reference", label: "Reference" },
];

export function Nav() {
  const path = usePathname();
  const router = useRouter();
  const isActive = (href: string) =>
    href === "/" ? path === "/" : path.startsWith(href);
  return (
    <div className="flex items-center justify-between bg-ink rounded-xl2 px-4 py-3 pl-5 animate-rise mb-1">
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
        <Link href="/reference" className="btn" style={{ background: "#26252e", color: "#eceaf2" }}>
          How it works
        </Link>
        <button className="btn btn-acc" onClick={() => router.push("/strategies/new")}>
          + New strategy
        </button>
      </div>
    </div>
  );
}
