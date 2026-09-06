/**
 * Tweens the numeric portion of an already-formatted string (e.g. "112.4", "+4.8%",
 * "₹4,820") from its previous value to its new one. Falls back to an immediate swap for
 * non-numeric text ("—", "…") and for prefers-reduced-motion — this is a cosmetic
 * transition on values that are computed and displayed exactly as before, never a
 * source of the number itself.
 */

import { useEffect, useRef, useState } from "react";

const NUMBER_RE = /-?[\d,]+\.?\d*/;

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useCountUpText(value: string, durationMs = 600): string {
  const [display, setDisplay] = useState(value);
  const prevNumRef = useRef<number | null>(null);
  const frameRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const match = NUMBER_RE.exec(value);
    if (match === null || prefersReducedMotion()) {
      setDisplay(value);
      prevNumRef.current = match !== null ? Number(match[0].replace(/,/g, "")) : null;
      return;
    }

    const raw = match[0];
    const index = match.index;
    const target = Number(raw.replace(/,/g, ""));
    const decimals = (raw.split(".")[1] ?? "").length;
    const from = prevNumRef.current ?? target;
    const start = performance.now();

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      const current = from + (target - from) * eased;
      const formatted = current.toLocaleString("en-IN", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      });
      setDisplay(value.slice(0, index) + formatted + value.slice(index + raw.length));
      if (t < 1) {
        frameRef.current = requestAnimationFrame(tick);
      } else {
        prevNumRef.current = target;
      }
    };
    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current !== undefined) cancelAnimationFrame(frameRef.current);
    };
  }, [value, durationMs]);

  return display;
}
