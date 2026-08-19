import { useLocales } from 'expo-localization';
import {
  createContext,
  useContext,
  useMemo,
  type PropsWithChildren,
} from 'react';
import { StyleSheet, View } from 'react-native';

import { resolveLocalization, type LocalizationResolution } from './locale';
import {
  englishMessages,
  type CompatibleMessageCatalog,
} from './messages';
import {
  createPseudoMessageCatalog,
  type PseudoLocale,
} from './pseudolocale';

type LocalizationContextValue = LocalizationResolution & Readonly<{
  messages: Readonly<CompatibleMessageCatalog>;
}>;

const DEFAULT_CONTEXT: LocalizationContextValue = Object.freeze({
  ...resolveLocalization([]),
  messages: englishMessages,
});

const LocalizationContext = createContext<LocalizationContextValue>(DEFAULT_CONTEXT);

export function LocalizationProvider({
  children,
  pseudoLocale = null,
}: PropsWithChildren<{ pseudoLocale?: PseudoLocale | null }>) {
  const deviceLocales = useLocales();
  const resolution = useMemo(
    () => resolveLocalization(deviceLocales, pseudoLocale),
    [deviceLocales, pseudoLocale],
  );
  const messages = useMemo(
    () => pseudoLocale ? createPseudoMessageCatalog(pseudoLocale) : englishMessages,
    [pseudoLocale],
  );
  const value = useMemo(
    () => ({ ...resolution, messages }),
    [messages, resolution],
  );

  return (
    <LocalizationContext.Provider value={value}>
      <View
        testID="localization-layout-root"
        style={[styles.root, { direction: resolution.direction }]}
      >
        {children}
      </View>
    </LocalizationContext.Provider>
  );
}

export function useLocalization(): LocalizationContextValue {
  return useContext(LocalizationContext);
}

export function useMessages(): Readonly<CompatibleMessageCatalog> {
  return useLocalization().messages;
}

const styles = StyleSheet.create({ root: { flex: 1 } });
