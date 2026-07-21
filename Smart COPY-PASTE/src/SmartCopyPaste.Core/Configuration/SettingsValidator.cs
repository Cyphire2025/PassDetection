using SmartCopyPaste.Core.Contracts;

namespace SmartCopyPaste.Core.Configuration;

public static class SettingsValidator
{
    private const HotkeyModifiers AllModifiers =
        HotkeyModifiers.Alt
        | HotkeyModifiers.Control
        | HotkeyModifiers.Shift
        | HotkeyModifiers.Windows;

    private static readonly HashSet<string> NamedKeys = new(
        [
            "BACKSPACE",
            "DELETE",
            "DOWN",
            "END",
            "ESCAPE",
            "HOME",
            "INSERT",
            "LEFT",
            "PAGEDOWN",
            "PAGEUP",
            "RIGHT",
            "SPACE",
            "TAB",
            "UP",
        ],
        StringComparer.Ordinal);

    public static SettingsValidationResult Validate(AppSettings settings)
    {
        ArgumentNullException.ThrowIfNull(settings);
        var issues = new List<SettingsValidationIssue>();
        if (settings.SchemaVersion != ContractVersions.Settings)
        {
            issues.Add(new SettingsValidationIssue(
                "SETTINGS_SCHEMA_UNSUPPORTED",
                nameof(settings.SchemaVersion),
                "The settings schema version is unsupported."));
        }

        if (settings.Hotkeys is null)
        {
            issues.Add(new SettingsValidationIssue(
                "HOTKEYS_REQUIRED",
                nameof(settings.Hotkeys),
                "Shortcut settings are required."));
        }
        else
        {
            ValidateHotkeys(settings.Hotkeys, issues);
        }

        if (settings.InactivityTimeout < TimeSpan.FromMinutes(1)
            || settings.InactivityTimeout > TimeSpan.FromHours(24))
        {
            issues.Add(new SettingsValidationIssue(
                "INACTIVITY_TIMEOUT_INVALID",
                nameof(settings.InactivityTimeout),
                "The inactivity timeout must be between 1 minute and 24 hours."));
        }

        if (settings.AllowedBrowserProcesses is null
            || settings.AllowedBrowserProcesses.Count == 0)
        {
            issues.Add(new SettingsValidationIssue(
                "ALLOWED_BROWSERS_REQUIRED",
                nameof(settings.AllowedBrowserProcesses),
                "At least one browser process must be allowed."));
        }
        else
        {
            ValidateAllowedProcesses(settings.AllowedBrowserProcesses, issues);
        }

        return new SettingsValidationResult(issues.AsReadOnly());
    }

    public static bool IsValidGesture(HotkeyGesture gesture)
    {
        ArgumentNullException.ThrowIfNull(gesture);
        var issues = new List<SettingsValidationIssue>();
        ValidateGesture("Gesture", gesture, issues);
        return issues.Count == 0;
    }

    private static void ValidateHotkeys(
        HotkeySettings hotkeys,
        List<SettingsValidationIssue> issues)
    {
        IReadOnlyDictionary<string, HotkeyGesture> bindings = hotkeys.AsNamedBindings();
        foreach ((string name, HotkeyGesture gesture) in bindings)
        {
            ValidateGesture($"Hotkeys.{name}", gesture, issues);
        }

        foreach (IGrouping<string, KeyValuePair<string, HotkeyGesture>> duplicate
                 in bindings.GroupBy(
                     binding => GestureIdentity(binding.Value),
                     StringComparer.Ordinal)
                     .Where(group => group.Count() > 1))
        {
            string names = string.Join(
                ", ",
                duplicate.Select(binding => binding.Key).Order(StringComparer.Ordinal));
            issues.Add(new SettingsValidationIssue(
                "HOTKEY_CONFLICT",
                "Hotkeys",
                $"The same shortcut is assigned to: {names}."));
        }
    }

    private static void ValidateGesture(
        string property,
        HotkeyGesture gesture,
        List<SettingsValidationIssue> issues)
    {
        if (gesture is null)
        {
            issues.Add(new SettingsValidationIssue(
                "HOTKEY_REQUIRED",
                property,
                "A shortcut is required."));
            return;
        }

        if ((gesture.Modifiers & ~AllModifiers) != 0)
        {
            issues.Add(new SettingsValidationIssue(
                "HOTKEY_MODIFIERS_INVALID",
                property,
                "The shortcut contains unsupported modifier flags."));
        }

        string key = gesture.NormalizedKey;
        if (!IsSupportedKey(key))
        {
            issues.Add(new SettingsValidationIssue(
                "HOTKEY_KEY_INVALID",
                property,
                "The shortcut key is not supported."));
            return;
        }

        int protectiveModifierCount = CountProtectiveModifiers(gesture.Modifiers);
        if (protectiveModifierCount < 2)
        {
            issues.Add(new SettingsValidationIssue(
                "HOTKEY_CHORD_UNSAFE",
                property,
                "Use at least two of Ctrl, Alt, and Shift (for example Ctrl+Alt) so routine typing and navigation cannot trigger a global action."));
        }

        if (IsReservedGesture(gesture.Modifiers, key))
        {
            issues.Add(new SettingsValidationIssue(
                "HOTKEY_RESERVED",
                property,
                "This shortcut is reserved by Windows or unsafe to intercept."));
        }
    }

    private static void ValidateAllowedProcesses(
        IReadOnlyList<string> processes,
        List<SettingsValidationIssue> issues)
    {
        if (processes.Count > 16)
        {
            issues.Add(new SettingsValidationIssue(
                "TOO_MANY_ALLOWED_BROWSERS",
                "AllowedBrowserProcesses",
                "At most 16 browser processes may be configured."));
        }

        var unique = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        for (int index = 0; index < processes.Count; index++)
        {
            string process = processes[index] ?? string.Empty;
            if (process.Length is < 5 or > 64
                || !process.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
                || process.Contains('\\', StringComparison.Ordinal)
                || process.Contains('/', StringComparison.Ordinal)
                || process.Any(char.IsWhiteSpace))
            {
                issues.Add(new SettingsValidationIssue(
                    "ALLOWED_BROWSER_INVALID",
                    $"AllowedBrowserProcesses[{index}]",
                    "Use an executable file name without a path."));
                continue;
            }

            if (!unique.Add(process))
            {
                issues.Add(new SettingsValidationIssue(
                    "ALLOWED_BROWSER_DUPLICATE",
                    $"AllowedBrowserProcesses[{index}]",
                    "The browser process is listed more than once."));
            }
        }
    }

    private static bool IsSupportedKey(string key)
    {
        if (key.Length == 1 && char.IsLetterOrDigit(key[0]))
        {
            return true;
        }

        if (NamedKeys.Contains(key))
        {
            return true;
        }

        return key.Length is 2 or 3
            && key[0] == 'F'
            && int.TryParse(
                key.AsSpan(1),
                System.Globalization.NumberStyles.None,
                System.Globalization.CultureInfo.InvariantCulture,
                out int functionNumber)
            && functionNumber is >= 1 and <= 24;
    }

    private static bool IsReservedGesture(
        HotkeyModifiers modifiers,
        string key)
    {
        return key switch
        {
            "F4" when ContainsAll(modifiers, HotkeyModifiers.Alt) => true,
            "DELETE" when ContainsAll(
                modifiers,
                HotkeyModifiers.Control | HotkeyModifiers.Alt) => true,
            "ESCAPE" when ContainsAll(
                modifiers,
                HotkeyModifiers.Control | HotkeyModifiers.Shift) => true,
            "D" or "L" or "R" when ContainsAll(
                modifiers,
                HotkeyModifiers.Windows) => true,
            _ => false,
        };
    }

    private static int CountProtectiveModifiers(HotkeyModifiers modifiers)
    {
        int count = 0;
        if ((modifiers & HotkeyModifiers.Control) != 0)
        {
            count++;
        }

        if ((modifiers & HotkeyModifiers.Alt) != 0)
        {
            count++;
        }

        if ((modifiers & HotkeyModifiers.Shift) != 0)
        {
            count++;
        }

        return count;
    }

    private static bool ContainsAll(
        HotkeyModifiers actual,
        HotkeyModifiers required) =>
        (actual & required) == required;

    private static string GestureIdentity(HotkeyGesture gesture) =>
        $"{(int)gesture.Modifiers}:{gesture.NormalizedKey}";
}
