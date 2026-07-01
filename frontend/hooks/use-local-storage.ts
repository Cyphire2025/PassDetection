/**
 * useLocalStorage
 * ===============
 * React hook for type-safe localStorage access with SSR safety.
 *
 * Usage:
 *   const [theme, setTheme] = useLocalStorage("theme", "dark")
 */

import { useCallback, useState } from "react";

export function useLocalStorage<T>(
  key: string,
  initialValue: T
): [T, (value: T | ((prev: T) => T)) => void, () => void] {
  const [storedValue, setStoredValue] = useState<T>(() => {
    if (typeof window === "undefined") return initialValue;
    try {
      const item = window.localStorage.getItem(key);
      return item ? (JSON.parse(item) as T) : initialValue;
    } catch {
      return initialValue;
    }
  });

  const setValue = useCallback(
    (value: T | ((prev: T) => T)) => {
      setStoredValue((prev) => {
        const resolved = typeof value === "function"
          ? (value as (prev: T) => T)(prev)
          : value;
        try {
          window.localStorage.setItem(key, JSON.stringify(resolved));
        } catch {
          // Storage might be full or restricted — fail silently
        }
        return resolved;
      });
    },
    [key]
  );

  const removeValue = useCallback(() => {
    try {
      window.localStorage.removeItem(key);
      setStoredValue(initialValue);
    } catch {
      // Fail silently
    }
  }, [key, initialValue]);

  return [storedValue, setValue, removeValue];
}
