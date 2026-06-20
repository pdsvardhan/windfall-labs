"use client";

import { useEffect, useState } from "react";
import { StrategyBuilder } from "@/components/StrategyBuilder";
import type { StrategyConfig } from "@/lib/types";

// Reads an optional duplicate seed (set by the Strategies list) and prefills the builder in CREATE
// mode (no id), so "Duplicate" lands here with values filled instead of silently creating an entry.
export default function NewStrategy() {
  const [seed, setSeed] = useState<{ name: string; config: StrategyConfig } | null | undefined>(undefined);
  useEffect(() => {
    const raw = sessionStorage.getItem("wf_seed");
    if (raw) {
      try { setSeed(JSON.parse(raw)); } catch { setSeed(null); }
      sessionStorage.removeItem("wf_seed");
    } else setSeed(null);
  }, []);
  if (seed === undefined) return <div className="mt-8 text-muted text-sm">Loading…</div>;
  return <StrategyBuilder initial={seed ? { name: seed.name, config: seed.config } : undefined} />;
}
