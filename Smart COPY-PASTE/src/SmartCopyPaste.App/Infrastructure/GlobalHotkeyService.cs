using System.ComponentModel;
using System.Runtime.InteropServices;
using SmartCopyPaste.App.Interop;
using SmartCopyPaste.App.Models;

namespace SmartCopyPaste.App.Infrastructure;

internal sealed class GlobalHotkeyService : IDisposable
{
    private readonly HotkeyWindow window;
    private readonly HashSet<int> registeredIds = [];
    private bool disposed;

    internal GlobalHotkeyService()
    {
        window = new HotkeyWindow();
        window.HotkeyPressed += (_, id) =>
        {
            if (Enum.IsDefined((HotkeyCommand)id))
            {
                CommandPressed?.Invoke(this, (HotkeyCommand)id);
            }
        };
    }

    internal event EventHandler<HotkeyCommand>? CommandPressed;

    internal IReadOnlyList<string> Register(IReadOnlyDictionary<HotkeyCommand, HotkeySetting> hotkeys)
    {
        ArgumentNullException.ThrowIfNull(hotkeys);
        UnregisterAll();

        var failures = new List<string>();
        var gestures = new HashSet<(HotkeyModifiers Modifiers, int Key)>();
        foreach ((HotkeyCommand command, HotkeySetting setting) in hotkeys.OrderBy(static pair => pair.Key))
        {
            const HotkeyModifiers supportedModifiers =
                HotkeyModifiers.Alt |
                HotkeyModifiers.Control |
                HotkeyModifiers.Shift |
                HotkeyModifiers.Windows |
                HotkeyModifiers.NoRepeat;
            if (setting.VirtualKey is <= 0 or > 0xFE ||
                (setting.Modifiers & ~supportedModifiers) != HotkeyModifiers.None)
            {
                failures.Add($"{command}: invalid shortcut");
                continue;
            }

            HotkeyModifiers effectiveModifiers = setting.Modifiers | HotkeyModifiers.NoRepeat;
            if (!gestures.Add((effectiveModifiers, setting.VirtualKey)))
            {
                failures.Add($"{command}: duplicate shortcut {setting.DisplayName}");
                continue;
            }

            bool registered = NativeMethods.RegisterHotKey(
                window.Handle,
                (int)command,
                (uint)effectiveModifiers,
                (uint)setting.VirtualKey);
            if (!registered)
            {
                int error = Marshal.GetLastPInvokeError();
                failures.Add($"{command}: {setting.DisplayName} is unavailable ({new Win32Exception(error).Message})");
                continue;
            }

            registeredIds.Add((int)command);
        }

        return failures.AsReadOnly();
    }

    internal void UnregisterAll()
    {
        foreach (int id in registeredIds)
        {
            _ = NativeMethods.UnregisterHotKey(window.Handle, id);
        }

        registeredIds.Clear();
    }

    public void Dispose()
    {
        if (disposed)
        {
            return;
        }

        disposed = true;
        UnregisterAll();
        window.Dispose();
    }

    private sealed class HotkeyWindow : NativeWindow, IDisposable
    {
        private const int MessageOnlyWindow = -3;
        private bool disposed;

        internal HotkeyWindow()
        {
            CreateHandle(new CreateParams
            {
                Caption = "SmartCopyPaste.Hotkeys",
                Parent = new nint(MessageOnlyWindow),
            });
        }

        internal event EventHandler<int>? HotkeyPressed;

        protected override void WndProc(ref Message message)
        {
            if (message.Msg == NativeMethods.WmHotkey)
            {
                HotkeyPressed?.Invoke(this, message.WParam.ToInt32());
            }

            base.WndProc(ref message);
        }

        public void Dispose()
        {
            if (disposed)
            {
                return;
            }

            disposed = true;
            DestroyHandle();
        }
    }
}
