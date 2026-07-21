using SmartCopyPaste.Core.Configuration;
using SmartCopyPaste.Core.Contracts;

namespace SmartCopyPaste.Core.Tests;

public sealed class SettingsTests
{
    [Fact]
    public void SecureDefaults_AreValidAndVersioned()
    {
        AppSettings settings = AppSettings.Default;

        SettingsValidationResult result = SettingsValidator.Validate(settings);

        Assert.True(result.IsValid);
        Assert.Equal(ContractVersions.Settings, settings.SchemaVersion);
        Assert.Equal(TimeSpan.FromMinutes(30), settings.InactivityTimeout);
        Assert.True(settings.ClearOnWindowsLock);
        Assert.True(settings.ClearOnExit);
        Assert.False(settings.StartWithWindows);
        Assert.Contains("chrome.exe", settings.AllowedBrowserProcesses);
        Assert.Contains("msedge.exe", settings.AllowedBrowserProcesses);
    }

    [Fact]
    public void DuplicateShortcuts_AreRejected()
    {
        HotkeySettings defaults = HotkeySettings.Default;
        HotkeySettings duplicates = defaults with
        {
            SmartPaste = defaults.SmartCopy,
        };
        AppSettings settings = AppSettings.Default with { Hotkeys = duplicates };

        SettingsValidationResult result = SettingsValidator.Validate(settings);

        Assert.False(result.IsValid);
        Assert.Contains(result.Issues, issue => issue.Code == "HOTKEY_CONFLICT");
    }

    [Fact]
    public void WeakGlobalShortcut_IsRejected()
    {
        HotkeySettings hotkeys = HotkeySettings.Default with
        {
            SmartPaste = new HotkeyGesture(HotkeyModifiers.Shift, "V"),
        };

        SettingsValidationResult result = SettingsValidator.Validate(
            AppSettings.Default with { Hotkeys = hotkeys });

        Assert.Contains(
            result.Issues,
            issue => issue.Code == "HOTKEY_CHORD_UNSAFE");
    }

    [Theory]
    [InlineData(HotkeyModifiers.None, "SPACE")]
    [InlineData(HotkeyModifiers.None, "TAB")]
    [InlineData(HotkeyModifiers.None, "RIGHT")]
    [InlineData(HotkeyModifiers.Control, "A")]
    [InlineData(HotkeyModifiers.Shift, "F12")]
    [InlineData(HotkeyModifiers.Windows, "V")]
    public void RoutineOrSingleModifierGlobalShortcut_IsRejected(
        HotkeyModifiers modifiers,
        string key)
    {
        var gesture = new HotkeyGesture(modifiers, key);

        Assert.False(SettingsValidator.IsValidGesture(gesture));
    }

    [Theory]
    [InlineData(HotkeyModifiers.Control | HotkeyModifiers.Alt, "V")]
    [InlineData(HotkeyModifiers.Control | HotkeyModifiers.Shift, "F12")]
    [InlineData(HotkeyModifiers.Alt | HotkeyModifiers.Shift, "RIGHT")]
    public void TwoProtectiveModifierGlobalShortcut_IsAccepted(
        HotkeyModifiers modifiers,
        string key)
    {
        var gesture = new HotkeyGesture(modifiers, key);

        Assert.True(SettingsValidator.IsValidGesture(gesture));
    }

    [Fact]
    public void WindowsReservedShortcut_IsRejected()
    {
        HotkeySettings hotkeys = HotkeySettings.Default with
        {
            SmartPaste = new HotkeyGesture(
                HotkeyModifiers.Control | HotkeyModifiers.Alt,
                "DELETE"),
        };

        SettingsValidationResult result = SettingsValidator.Validate(
            AppSettings.Default with { Hotkeys = hotkeys });

        Assert.Contains(result.Issues, issue => issue.Code == "HOTKEY_RESERVED");
    }

    [Theory]
    [InlineData(HotkeyModifiers.Control | HotkeyModifiers.Alt | HotkeyModifiers.Shift, "DELETE")]
    [InlineData(HotkeyModifiers.Control | HotkeyModifiers.Alt | HotkeyModifiers.Shift, "ESCAPE")]
    [InlineData(HotkeyModifiers.Control | HotkeyModifiers.Alt | HotkeyModifiers.Shift, "F4")]
    public void ReservedShortcutWithAdditionalModifiers_IsRejected(
        HotkeyModifiers modifiers,
        string key)
    {
        var gesture = new HotkeyGesture(modifiers, key);

        Assert.False(SettingsValidator.IsValidGesture(gesture));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(1_441)]
    public void UnsafeInactivityTimeout_IsRejected(int minutes)
    {
        AppSettings settings = AppSettings.Default with
        {
            InactivityTimeout = TimeSpan.FromMinutes(minutes),
        };

        SettingsValidationResult result = SettingsValidator.Validate(settings);

        Assert.Contains(
            result.Issues,
            issue => issue.Code == "INACTIVITY_TIMEOUT_INVALID");
    }

    [Fact]
    public void BrowserAllowlist_AcceptsNamesButRejectsPathsAndDuplicates()
    {
        AppSettings settings = AppSettings.Default with
        {
            AllowedBrowserProcesses = new[]
            {
                @"C:\Program Files\Chrome\chrome.exe",
                "chrome.exe",
                "CHROME.EXE",
            },
        };

        SettingsValidationResult result = SettingsValidator.Validate(settings);

        Assert.Contains(
            result.Issues,
            issue => issue.Code == "ALLOWED_BROWSER_INVALID");
        Assert.Contains(
            result.Issues,
            issue => issue.Code == "ALLOWED_BROWSER_DUPLICATE");
    }

    [Fact]
    public void UnsupportedSettingsVersion_IsRejected()
    {
        SettingsValidationResult result = SettingsValidator.Validate(
            AppSettings.Default with { SchemaVersion = 999 });

        Assert.Contains(
            result.Issues,
            issue => issue.Code == "SETTINGS_SCHEMA_UNSUPPORTED");
    }

    [Theory]
    [InlineData("F1", true)]
    [InlineData("F24", true)]
    [InlineData("F25", false)]
    [InlineData("NOT_A_KEY", false)]
    public void GestureKeyValidation_IsDeterministic(string key, bool expected)
    {
        var gesture = new HotkeyGesture(
            HotkeyModifiers.Control | HotkeyModifiers.Alt,
            key);

        Assert.Equal(expected, SettingsValidator.IsValidGesture(gesture));
    }

    [Fact]
    public void VersionedMessage_RequiresExplicitSchemaAndCorrelation()
    {
        Guid correlationId = Guid.NewGuid();
        var message = new VersionedMessage<string>(
            1,
            "diagnostic.ping",
            correlationId,
            "ready");

        Assert.Equal(1, message.SchemaVersion);
        Assert.Equal("diagnostic.ping", message.MessageType);
        Assert.Equal(correlationId, message.CorrelationId);
        Assert.Equal("ready", message.Payload);
    }
}
