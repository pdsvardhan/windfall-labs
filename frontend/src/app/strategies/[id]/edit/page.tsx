"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import type { Strategy, StrategyConfig } from "@/lib/types";
import { StrategyBuilder } from "@/components/StrategyBuilder";
import { defaultConfig } from "@/lib/catalog";

export default function EditStrategy() {
  const id = String(useParams().id);
  const [s, setS] = useState<Strategy | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { api.getStrategy(id).then(setS).catch((e) => setErr(e.message)); }, [id]);

  if (err) return <div className="mt-8 text-loss text-sm">Could not load strategy: {err}</div>;
  if (!s) return <div className="mt-8 text-muted text-sm">Loading…</div>;
  // merge onto defaults so older/partial configs get all builder fields
  const config = { ...defaultConfig(s.name), ...(s.config as unknown as Partial<StrategyConfig>) } as StrategyConfig;
  return <StrategyBuilder initial={{ id: s.id, name: s.name, config }} />;
}
