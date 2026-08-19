import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';

export function useRouteFocus(): boolean {
  const [focused, setFocused] = useState(false);

  useFocusEffect(useCallback(() => {
    setFocused(true);
    return () => setFocused(false);
  }, []));

  return focused;
}
