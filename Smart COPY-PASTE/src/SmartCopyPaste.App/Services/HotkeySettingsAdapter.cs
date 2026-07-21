using SmartCopyPaste.App.Models;
using CoreConfiguration = SmartCopyPaste.Core.Configuration;

namespace SmartCopyPaste.App.Services;

internal static class HotkeySettingsAdapter
{
    internal static CoreConfiguration.AppSettings ToCoreSettings(PersistedAppSettings settings)
    {
        ArgumentNullException.ThrowIfNull(settings);
        CoreConfiguration.HotkeyGesture Gesture(HotkeyCommand command)
        {
            if (!settings.Hotkeys.TryGetValue(command, out HotkeySetting? hotkey) ||
                hotkey is null)
            {
                throw new InvalidDataException($"The {command} shortcut is missing.");
            }

            return new CoreConfiguration.HotkeyGesture(
                ToCoreModifiers(hotkey.Modifiers),
                ToKeyName(hotkey.VirtualKey));
        }

        var hotkeys = new CoreConfiguration.HotkeySettings(
            Gesture(HotkeyCommand.CaptureHeaders),
            Gesture(HotkeyCommand.SmartCopy),
            Gesture(HotkeyCommand.SmartPaste),
            Gesture(HotkeyCommand.OpenPicker),
            Gesture(HotkeyCommand.NextPassenger),
            Gesture(HotkeyCommand.PreviousPassenger),
            Gesture(HotkeyCommand.ClearActivePassenger),
            Gesture(HotkeyCommand.PauseResume));
        return new CoreConfiguration.AppSettings(
            SmartCopyPaste.Core.Contracts.ContractVersions.Settings,
            hotkeys,
            TimeSpan.FromMinutes(settings.InactivityMinutes),
            ClearOnWindowsLock: true,
            ClearOnExit: true,
            settings.StartWithWindows,
            Array.AsReadOnly(["chrome.exe", "msedge.exe", "brave.exe"]));
    }

    internal static Dictionary<HotkeyCommand, HotkeySetting> Clone(
        IReadOnlyDictionary<HotkeyCommand, HotkeySetting> source)
    {
        ArgumentNullException.ThrowIfNull(source);
        return source.ToDictionary(
            static pair => pair.Key,
            static pair => new HotkeySetting
            {
                Modifiers = pair.Value.Modifiers & ~HotkeyModifiers.NoRepeat,
                VirtualKey = pair.Value.VirtualKey,
                DisplayName = pair.Value.DisplayName,
            });
    }

    internal static string Format(HotkeyModifiers modifiers, int virtualKey)
    {
        var parts = new List<string>();
        if ((modifiers & HotkeyModifiers.Control) != 0)
        {
            parts.Add("Ctrl");
        }

        if ((modifiers & HotkeyModifiers.Alt) != 0)
        {
            parts.Add("Alt");
        }

        if ((modifiers & HotkeyModifiers.Shift) != 0)
        {
            parts.Add("Shift");
        }

        if ((modifiers & HotkeyModifiers.Windows) != 0)
        {
            parts.Add("Win");
        }

        parts.Add(ToKeyName(virtualKey));
        return string.Join("+", parts);
    }

    private static CoreConfiguration.HotkeyModifiers ToCoreModifiers(HotkeyModifiers modifiers)
    {
        CoreConfiguration.HotkeyModifiers converted = CoreConfiguration.HotkeyModifiers.None;
        if ((modifiers & HotkeyModifiers.Alt) != 0)
        {
            converted |= CoreConfiguration.HotkeyModifiers.Alt;
        }

        if ((modifiers & HotkeyModifiers.Control) != 0)
        {
            converted |= CoreConfiguration.HotkeyModifiers.Control;
        }

        if ((modifiers & HotkeyModifiers.Shift) != 0)
        {
            converted |= CoreConfiguration.HotkeyModifiers.Shift;
        }

        if ((modifiers & HotkeyModifiers.Windows) != 0)
        {
            converted |= CoreConfiguration.HotkeyModifiers.Windows;
        }

        return converted;
    }

    private static string ToKeyName(int virtualKey)
    {
        Keys key = (Keys)virtualKey;
        if (key is >= Keys.A and <= Keys.Z)
        {
            return key.ToString();
        }

        if (key is >= Keys.D0 and <= Keys.D9)
        {
            return ((int)key - (int)Keys.D0)
                .ToString(System.Globalization.CultureInfo.InvariantCulture);
        }

        if (key is >= Keys.F1 and <= Keys.F24)
        {
            return key.ToString();
        }

        return key switch
        {
            Keys.Back => "BACKSPACE",
            Keys.Delete => "DELETE",
            Keys.Down => "DOWN",
            Keys.End => "END",
            Keys.Escape => "ESCAPE",
            Keys.Home => "HOME",
            Keys.Insert => "INSERT",
            Keys.Left => "LEFT",
            Keys.Next => "PAGEDOWN",
            Keys.Prior => "PAGEUP",
            Keys.Right => "RIGHT",
            Keys.Space => "SPACE",
            Keys.Tab => "TAB",
            Keys.Up => "UP",
            _ => key.ToString().ToUpperInvariant(),
        };
    }
}
