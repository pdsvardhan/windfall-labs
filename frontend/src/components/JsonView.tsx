"use client";

// Syntax-highlighted read-only view of the strategy config (dark "Live config" pane).
function hl(json: string): string {
  return json
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/("(?:[^"\\]|\\.)*?")(\s*:)/g, '<span style="color:#9f86ee">$1</span>$2')
    .replace(/(:\s*)("(?:[^"\\]|\\.)*?")/g, '$1<span style="color:#9ad36a">$2</span>')
    .replace(/\b(true|false)\b/g, '<span style="color:#f5a35a">$1</span>')
    .replace(/(:\s*)(-?\d+\.?\d*)/g, '$1<span style="color:#f48fc6">$2</span>');
}

// maxHeight is optional: when omitted (or 0) the pane grows naturally with the content
// (B-BLD-JSON-SCROLL — no out-of-place vertical scrollbar). Pass a number to cap + scroll.
export function JsonView({ value, maxHeight }: { value: unknown; maxHeight?: number }) {
  const json = JSON.stringify(value, null, 2);
  const cap = !!maxHeight && maxHeight > 0;
  return (
    <div className="rounded-xl" style={{ background: "#100f17", padding: "14px 16px", ...(cap ? { maxHeight, overflow: "auto" } : {}) }}>
      <pre className="wf-jsonpre" dangerouslySetInnerHTML={{ __html: hl(json) }} />
    </div>
  );
}
