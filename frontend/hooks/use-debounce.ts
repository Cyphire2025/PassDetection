/**
 * useDebounce
 * ===========
 * Debounces a value by the specified delay.
 * Used for search inputs to avoid excessive API calls.
 *
 * Usage:
 *   const debouncedSearch = useDebounce(searchTerm, 400)
 */

import { useEffect, useState } from "react";

export function useDebounce<T>(value: T, delayMs: number = 400): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedValue(value);
    }, delayMs);

    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debouncedValue;
}
