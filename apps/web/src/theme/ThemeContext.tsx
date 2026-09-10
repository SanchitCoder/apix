/**
 * Theme state — light only. The dashboard shell (navy header/sidebar, white cards) is a
 * fixed light design with no dark-mode toggle exposed anywhere in the UI, so this no
 * longer follows the OS preference or a stored value: doing so previously flipped every
 * `bg-surface` panel to near-black for anyone on a dark system theme, and skewed chart
 * colours to the dark palette against a light background. `index.css` defines light
 * values only now. Re-introduce preference switching only alongside a real toggle.
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

const MODE: ThemeMode = "light";

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
        /* no-op until a real dark-mode toggle exists */
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
