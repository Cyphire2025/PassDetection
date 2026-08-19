import { render } from '@testing-library/react-native';
import { Text } from 'react-native';

import {
  LocalizationProvider,
  useLocalization,
} from '../localization-provider';

function LocalizationProbe() {
  const localization = useLocalization();
  return (
    <Text testID="localized-copy">
      {`${localization.direction}:${localization.formattingLocale}:${localization.messages.tryAgain()}`}
    </Text>
  );
}

describe('LocalizationProvider', () => {
  it('uses Expo device locale preferences for reviewed English copy', async () => {
    const view = await render(<LocalizationProvider><LocalizationProbe /></LocalizationProvider>);

    expect(view.getByTestId('localized-copy')).toHaveTextContent('ltr:en-US:Try again');
    expect(view.getByTestId('localization-layout-root')).toHaveStyle({ direction: 'ltr' });
  });

  it('supports an explicit RTL pseudolocale without shipping invented copy', async () => {
    const view = await render(
      <LocalizationProvider pseudoLocale="ar-XB">
        <LocalizationProbe />
      </LocalizationProvider>,
    );

    expect(view.getByTestId('localized-copy')).toHaveTextContent(/^rtl:en-IN:⟦/);
    expect(view.getByTestId('localization-layout-root')).toHaveStyle({ direction: 'rtl' });
  });
});
