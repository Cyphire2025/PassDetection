import { fireEvent, render } from '@testing-library/react-native';
import { useState } from 'react';

import { OtpCodeInput } from '../otp-code-input';

function Harness() {
  const [value, setValue] = useState('');
  return <OtpCodeInput value={value} onChange={setValue} />;
}

test('distributes an OTP paste across six visible boxes', async () => {
  const screen = await render(<Harness />);

  await fireEvent.changeText(screen.getByLabelText('Verification code digit 1'), '123456');

  for (let index = 1; index <= 6; index += 1) {
    expect(screen.getByLabelText(`Verification code digit ${index}`).props.value).toBe(String(index));
  }
});

test('moves backward and clears the previous digit on an empty-box backspace', async () => {
  const screen = await render(<Harness />);
  await fireEvent.changeText(screen.getByLabelText('Verification code digit 1'), '12');

  await fireEvent(screen.getByLabelText('Verification code digit 3'), 'keyPress', {
    nativeEvent: { key: 'Backspace' },
  });

  expect(screen.getByLabelText('Verification code digit 1').props.value).toBe('1');
  expect(screen.getByLabelText('Verification code digit 2').props.value).toBe('');
});
