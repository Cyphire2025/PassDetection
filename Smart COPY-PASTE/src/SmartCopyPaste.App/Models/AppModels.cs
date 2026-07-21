namespace SmartCopyPaste.App.Models;

[Flags]
internal enum HotkeyModifiers : uint
{
    None = 0,
    Alt = 0x0001,
    Control = 0x0002,
    Shift = 0x0004,
    Windows = 0x0008,
    NoRepeat = 0x4000,
}

internal enum HotkeyCommand
{
    CaptureHeaders = 1,
    SmartCopy = 2,
    SmartPaste = 3,
    OpenPicker = 4,
    NextPassenger = 5,
    PreviousPassenger = 6,
    PauseResume = 7,
    ClearActivePassenger = 8,
}

internal sealed class HotkeySetting
{
    public HotkeyModifiers Modifiers { get; set; }

    public int VirtualKey { get; set; }

    public string DisplayName { get; set; } = string.Empty;
}

internal sealed class HeaderColumnRecord
{
    public int Offset { get; set; }

    public string OriginalHeader { get; set; } = string.Empty;

    public string CanonicalFieldId { get; set; } = string.Empty;

    public bool Ignored { get; set; }
}

internal sealed class HeaderTemplateRecord
{
    public int SchemaVersion { get; set; } = 1;

    public string TemplateId { get; set; } = Guid.NewGuid().ToString("N");

    public string DisplayName { get; set; } = string.Empty;

    public string WorkbookIdentity { get; set; } = string.Empty;

    public string WorksheetIdentity { get; set; } = string.Empty;

    public int HeaderRow { get; set; }

    public int FirstColumn { get; set; }

    public int ColumnCount { get; set; }

    public string HeaderFingerprint { get; set; } = string.Empty;

    public bool SessionOnly { get; set; }

    public List<HeaderColumnRecord> Columns { get; set; } = [];
}

internal sealed class PersistedAppSettings
{
    public int SchemaVersion { get; set; } = 1;

    public string ProtectedUserSecret { get; set; } = string.Empty;

    public bool StartWithWindows { get; set; }

    public int InactivityMinutes { get; set; } = 30;

    public string? ActiveFallbackTemplateId { get; set; }

    public Dictionary<HotkeyCommand, HotkeySetting> Hotkeys { get; set; } = CreateDefaultHotkeys();

    public Dictionary<string, string> CustomHeaderAliases { get; set; } =
        new(StringComparer.OrdinalIgnoreCase);

    public List<HeaderTemplateRecord> HeaderTemplates { get; set; } = [];

    public static Dictionary<HotkeyCommand, HotkeySetting> CreateDefaultHotkeys() =>
        new()
        {
            [HotkeyCommand.CaptureHeaders] = Gesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, Keys.H, "Ctrl+Alt+H"),
            [HotkeyCommand.SmartCopy] = Gesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, Keys.C, "Ctrl+Alt+C"),
            [HotkeyCommand.SmartPaste] = Gesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, Keys.V, "Ctrl+Alt+V"),
            [HotkeyCommand.OpenPicker] = Gesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, Keys.P, "Ctrl+Alt+P"),
            [HotkeyCommand.NextPassenger] = Gesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, Keys.Right, "Ctrl+Alt+Right"),
            [HotkeyCommand.PreviousPassenger] = Gesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, Keys.Left, "Ctrl+Alt+Left"),
            [HotkeyCommand.PauseResume] = Gesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, Keys.Space, "Ctrl+Alt+Space"),
            [HotkeyCommand.ClearActivePassenger] = Gesture(HotkeyModifiers.Control | HotkeyModifiers.Alt, Keys.X, "Ctrl+Alt+X"),
        };

    private static HotkeySetting Gesture(HotkeyModifiers modifiers, Keys key, string displayName) =>
        new()
        {
            Modifiers = modifiers,
            VirtualKey = (int)key,
            DisplayName = displayName,
        };
}

internal sealed record FocusedFieldSnapshot(
    string ProcessName,
    int ProcessId,
    nint ForegroundWindow,
    string AccessibleName,
    string AutomationId,
    string HelpText,
    string ClassName,
    string ControlType,
    string RuntimeIdentity,
    bool IsPassword,
    bool IsEnabled,
    bool IsReadOnly,
    bool IsKeyboardFocusable,
    bool IsEditable,
    string Placeholder,
    string SectionHeading,
    string InputType,
    string FormatHint,
    Rectangle BoundingRectangle,
    string TargetToken);

internal sealed record SettingsLoadResult(PersistedAppSettings Settings, string? Warning);
