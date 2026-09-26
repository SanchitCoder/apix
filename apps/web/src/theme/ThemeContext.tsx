/**
 * Theme state — dark only, and fixed, not OS-driven. The dashboard was reskinned to a
 * dark "statistical monitoring terminal" look (index.css / theme/tokens.ts's DARK
 * export); this file hard-codes that choice by always stamping
 * `data-theme="dark"` itself, exactly the way this codebase previously hard-coded
 * light: an earlier version *followed* `prefers-color-scheme`, which flipped every
 * `bg-surface` panel to near-black for anyone on a dark OS theme whether or not the
 * light design was ready for it. The fix here is the same shape, just the other
 * direction — an explicit, reviewed value the app sets on itself, never a media query
 * silently deciding for it. Re-introduce preference switching only alongside a real,
 * user-facing toggle that sets this deliberately.
 */

import { createContext, useContext, useEffect, useMemo } from "react";
import type { ReactNode } from "react";
import { tokensFor } from "./tokens";
import type { ThemeMode, ThemeTokens } from "./tokens";

type ThemePreference = ThemeMode | "system";

interface ThemeContextValue {
  preference: ThemePreference;
  mode: ThemeMode;
  tokens: ThemeTokens;
  setPreference: (preference: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const MODE: ThemeMode = "dark";

export function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.dataset["theme"] = MODE;
    document.documentElement.style.colorScheme = MODE;
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      preference: MODE,
      mode: MODE,
      tokens: tokensFor(MODE),
      setPreference: () => {
        /* no-op until a real light-mode toggle exists */
      },
    }),
    [],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (value === null) throw new Error("useTheme called outside ThemeProvider");
  return value;
}
