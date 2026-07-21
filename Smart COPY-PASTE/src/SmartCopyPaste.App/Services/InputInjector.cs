using SmartCopyPaste.App.Interop;

namespace SmartCopyPaste.App.Services;

internal static class InputInjector
{
    private const int ModifierReleaseTimeoutMilliseconds = 1200;

    internal static async Task<bool> WaitForShortcutReleaseAsync(CancellationToken cancellationToken)
    {
        long started = Environment.TickCount64;
        while (!NativeMethods.AreShortcutModifiersReleased())
        {
            if (Environment.TickCount64 - started > ModifierReleaseTimeoutMilliseconds)
            {
                return false;
            }

            await Task.Delay(15, cancellationToken).ConfigureAwait(true);
        }

        return true;
    }

    internal static void SendControlShortcut(Keys key, nint expectedForegroundWindow)
    {
        EnsureTargetStillForeground(expectedForegroundWindow);
        NativeMethods.Input[] inputs =
        [
            CreateVirtualKeyInput(Keys.ControlKey, keyUp: false),
            CreateVirtualKeyInput(key, keyUp: false),
            CreateVirtualKeyInput(key, keyUp: true),
            CreateVirtualKeyInput(Keys.ControlKey, keyUp: true),
        ];
        NativeMethods.ThrowIfSendInputIncomplete(inputs);
    }

    internal static void EnsureTargetStillForeground(nint expectedForegroundWindow)
    {
        if (expectedForegroundWindow == nint.Zero ||
            NativeMethods.GetForegroundWindow() != expectedForegroundWindow)
        {
            throw new InvalidOperationException("The selected field lost focus. Click it and try again.");
        }
    }

    private static NativeMethods.Input CreateVirtualKeyInput(Keys key, bool keyUp) =>
        new()
        {
            Type = NativeMethods.InputKeyboard,
            Data = new NativeMethods.InputUnion
            {
                Keyboard = new NativeMethods.KeyboardInput
                {
                    VirtualKey = (ushort)key,
                    Flags = keyUp ? NativeMethods.KeyeventfKeyup : 0,
                },
            },
        };
}
