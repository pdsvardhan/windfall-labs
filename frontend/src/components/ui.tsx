"use client";

import { useEffect, useRef, useState } from "react";

// ── animated count-up ───────────────────────────────────────────────────────
export function CountUp({ to, dec = 0, prefix = "", suffix = "", className = "" }:
  { to: number; dec?: number; prefix?: string; suffix?: string; className?: string }) {
  const [v, setV] = useState(0);
  useEffect(() => {
    let raf = 0; const t0 = performance.now(); const dur = 900;
    const step = (t: number) => {
      let p = Math.min(1, (t - t0) / dur); p = 1 - Math.pow(1 - p, 3);
      setV(to * p); if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step); return () => cancelAnimationFrame(raf);
  }, [to]);
  const txt = dec === 0 ? Math.round(v).toLocaleString("en-IN") : v.toFixed(dec);
  return <span className={`tn ${className}`}>{prefix}{txt}{suffix}</span>;
}

// ── cards ───────────────────────────────────────────────────────────────────
export function Card({ children, className = "", lift = false, style, onClick }:
  { children: React.ReactNode; className?: string; lift?: boolean; style?: React.CSSProperties; onClick?: () => void }) {
  return <div className={`wf-card ${lift ? "wf-card-lift" : ""} ${className}`} style={style} onClick={onClick}>{children}</div>;
}

const TONE: Record<string, { bg: string; label: string }> = {
  lime: { bg: "#b9d24a", label: "#5b6b1f" },
  limeY: { bg: "#f5e049", label: "#7d7220" },
  pink: { bg: "#f7b9dd", label: "#8c4a72" },
  sky: { bg: "#a9c9f2", label: "#345a87" },
  lilac: { bg: "#c4b6f7", label: "#4b3b86" },
  white: { bg: "#ffffff", label: "#7a7689" },
};

export function StatCard({ label, value, sub, tone = "white", delay = 0 }:
  { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: keyof typeof TONE; delay?: number }) {
  const t = TONE[tone];
  return (
    <div className="wf-card animate-pop" style={{ background: t.bg, padding: "20px 22px", animationDelay: `${delay}ms` }}>
      <div className="text-[13px] font-bold" style={{ color: t.label }}>{label}</div>
      <div className="text-[34px] font-extrabold mt-1.5 tracking-tight leading-none">{value}</div>
      {sub && <div className="text-[12px] mt-1.5 font-semibold" style={{ color: t.label }}>{sub}</div>}
    </div>
  );
}

// big colored metric card (backtest report)
export function MetricCard({ label, value, sub, tone = "lime", delay = 0 }:
  { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: keyof typeof TONE; delay?: number }) {
  return <StatCard label={label} value={value} sub={sub} tone={tone} delay={delay} />;
}

// small white metric chip
export function MetricMini({ label, value, valueClass = "" }:
  { label: string; value: React.ReactNode; valueClass?: string }) {
  return (
    <div className="wf-card" style={{ padding: "14px 16px" }}>
      <div className="text-[11.5px] text-faint font-semibold">{label}</div>
      <div className={`text-[22px] font-extrabold mt-1 ${valueClass}`}>{value}</div>
    </div>
  );
}

// ── form primitives ─────────────────────────────────────────────────────────
export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="text-[12px] font-bold text-muted">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-faint mt-1">{hint}</span>}
    </label>
  );
}

export function Switch({ on, onClick, disabled = false }: { on: boolean; onClick?: () => void; disabled?: boolean }) {
  return (
    <div className="wf-switch" data-on={on ? "1" : "0"} data-disabled={disabled ? "1" : "0"}
      onClick={() => !disabled && onClick?.()}><span /></div>
  );
}

export function Segmented<T extends string>({ value, options, onChange }:
  { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="flex gap-1 mt-1.5 p-1 rounded-[11px]" style={{ background: "#f1eef8" }}>
      {options.map((o) => (
        <span key={o.value} className="wf-seg" data-active={value === o.value ? "1" : "0"} onClick={() => onChange(o.value)}>
          {o.label}
        </span>
      ))}
    </div>
  );
}

export function Slider({ value, min, max, step = 1, onChange }:
  { value: number; min: number; max: number; step?: number; onChange: (v: number) => void }) {
  return (
    <input type="range" className="wf-range mt-2" min={min} max={max} step={step} value={value}
      onChange={(e) => onChange(parseFloat(e.target.value))} />
  );
}

export function SectionTitle({ dot, children }: { dot?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2.5 mb-4">
      {dot && <span className="w-[11px] h-[11px] rounded" style={{ background: dot }} />}
      <span className="font-extrabold text-[15px]">{children}</span>
    </div>
  );
}

export function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "buy" | "sell" | "hold" | "good" | "bad" | "warn" | "neutral" }) {
  const map: Record<string, string> = {
    buy: "background:#daf0c8;color:#3f7d1c", sell: "background:#fde2ec;color:#c23e74",
    hold: "background:#dfeafe;color:#345a87", good: "background:#e6f4ea;color:#1f7a4d",
    bad: "background:#fdeaf1;color:#c23e74", warn: "background:#fff3da;color:#9a6c12",
    neutral: "background:#eceaf2;color:#7a7689",
  };
  const css = Object.fromEntries(map[tone].split(";").map((p) => p.split(":"))) as React.CSSProperties;
  return <span className="text-[11px] font-extrabold px-2.5 py-1 rounded-full" style={css}>{children}</span>;
}

// ── kebab menu (⋯ dropdown) ──────────────────────────────────────────────────
export function Menu({ items, label = "⋯", align = "right" }:
  { items: { label: string; onClick: () => void; danger?: boolean }[]; label?: string; align?: "left" | "right" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onEsc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc); document.addEventListener("keydown", onEsc);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onEsc); };
  }, [open]);
  return (
    <div className="wf-menuwrap" ref={ref}>
      <button type="button" className="wf-menubtn" aria-haspopup="menu" aria-expanded={open}
        aria-label="More actions" onClick={() => setOpen((o) => !o)}>{label}</button>
      {open && (
        <div className="wf-menu" role="menu" style={align === "left" ? { left: 0 } : { right: 0 }}>
          {items.map((it, k) => (
            <button key={k} type="button" role="menuitem" className={`wf-menu-item ${it.danger ? "danger" : ""}`}
              onClick={() => { setOpen(false); it.onClick(); }}>{it.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── modal overlay ────────────────────────────────────────────────────────────
export function Modal({ open, onClose, title, children, wide = false }:
  { open: boolean; onClose: () => void; title?: React.ReactNode; children: React.ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const onEsc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="wf-overlay" onMouseDown={onClose}>
      <div className={`wf-modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}>
        {title && <div className="text-[16px] font-extrabold mb-3">{title}</div>}
        {children}
      </div>
    </div>
  );
}

// ── confirm dialog (destructive actions) ─────────────────────────────────────
export function ConfirmDialog({ open, title = "Are you sure?", body, confirmLabel = "Delete",
  cancelLabel = "Cancel", danger = true, onConfirm, onCancel }:
  { open: boolean; title?: string; body?: React.ReactNode; confirmLabel?: string; cancelLabel?: string;
    danger?: boolean; onConfirm: () => void; onCancel: () => void }) {
  return (
    <Modal open={open} onClose={onCancel} title={title}>
      {body && <div className="text-[13px] text-muted mb-4">{body}</div>}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn btn-ghost" onClick={onCancel}>{cancelLabel}</button>
        <button type="button" className={`btn ${danger ? "btn-danger" : "btn-ink"}`} onClick={onConfirm}>{confirmLabel}</button>
      </div>
    </Modal>
  );
}

// reveal-on-mount wrapper (light)
export function useReveal() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    el.style.opacity = "0"; el.style.transform = "translateY(16px)";
    const id = requestAnimationFrame(() => {
      el.style.transition = "opacity .5s ease, transform .5s ease";
      el.style.opacity = "1"; el.style.transform = "none";
    });
    return () => cancelAnimationFrame(id);
  }, []);
  return ref;
}
