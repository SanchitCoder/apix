/** Inline style carrying the --reveal-i custom property the .reveal keyframe reads for stagger. */

import type { CSSProperties } from "react";

export function revealStyle(index: number): CSSProperties {
  return { "--reveal-i": index } as unknown as CSSProperties;
}
