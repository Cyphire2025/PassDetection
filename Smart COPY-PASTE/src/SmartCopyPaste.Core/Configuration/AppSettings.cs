using System.Collections.ObjectModel;
using SmartCopyPaste.Core.Contracts;

namespace SmartCopyPaste.Core.Configuration;

[Flags]
public enum HotkeyModifiers
{
    None = 0,
    Alt = 1,
    Control = 2,
    Shift = 4,
    Windows = 8,
}

public sealed record HotkeyGesture(
    HotkeyModifiers Modifiers,
    string Key)
{
    public string NormalizedKey => Key?.Trim().ToUpperInvariant() ?? string.Empty;

    public override string ToString() =>
        $"{Modifiers}+{NormalizedKey}";
}

public sealed record HotkeySettings(
    HotkeyGesture SetHeaders,
    HotkeyGesture SmartCopy,
    HotkeyGesture SmartPaste,
    HotkeyGesture OpenPicker,
    HotkeyGesture NextPassenger,
    HotkeyGesture PreviousPassenger,
    HotkeyGesture ClearActivePassenger,
    HotkeyGesture TogglePause)
{
    public static HotkeySettings Default { get; } = new(
        new HotkeyGesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, "H"),
        new HotkeyGesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, "C"),
        new HotkeyGesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, "V"),
        new HotkeyGesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, "P"),
        new HotkeyGesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, "RIGHT"),
        new HotkeyGesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, "LEFT"),
        new HotkeyGesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, "X"),
        new HotkeyGesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, "SPACE"));

    public IReadOnlyDictionary<string, HotkeyGesture> AsNamedBindings() =>
        new ReadOnlyDictionary<string, HotkeyGesture>(
            new Dictionary<string, HotkeyGesture>(StringComparer.Ordinal)
            {
                [nameof(SetHeaders)] = SetHeaders,
                [nameof(SmartCopy)] = SmartCopy,
                [nameof(SmartPaste)] = SmartPaste,
                [nameof(OpenPicker)] = OpenPicker,
                [nameof(NextPassenger)] = NextPassenger,
                [nameof(PreviousPassenger)] = PreviousPassenger,
                [nameof(ClearActivePassenger)] = ClearActivePassenger,
                [nameof(TogglePause)] = TogglePause,
            });
}

public sealed record AppSettings(
    int SchemaVersion,
    HotkeySettings Hotkeys,
    TimeSpan InactivityTimeout,
    bool ClearOnWindowsLock,
    bool ClearOnExit,
    bool StartWithWindows,
    IReadOnlyList<string> AllowedBrowserProcesses)
{
    public static AppSettings Default { get; } = new(
        ContractVersions.Settings,
        HotkeySettings.Default,
        TimeSpan.FromMinutes(30),
        ClearOnWindowsLock: true,
        ClearOnExit: true,
        StartWithWindows: false,
        Array.AsReadOnly(["chrome.exe", "msedge.exe"]));
}

public sealed record SettingsValidationIssue(
    string Code,
    string Property,
    string Message);

public sealed record SettingsValidationResult(
    IReadOnlyList<SettingsValidationIssue> Issues)
{
    public bool IsValid => Issues.Count == 0;
}
