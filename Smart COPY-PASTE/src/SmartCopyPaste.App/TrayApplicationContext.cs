using Microsoft.Win32;
using SmartCopyPaste.App.Forms;
using SmartCopyPaste.App.Infrastructure;
using SmartCopyPaste.App.Models;
using SmartCopyPaste.App.Services;
using SmartCopyPaste.Core.Catalog;
using SmartCopyPaste.Core.Matching;
using SmartCopyPaste.Core.Parsing;
using SmartCopyPaste.Core.Session;

namespace SmartCopyPaste.App;

internal sealed partial class TrayApplicationContext : ApplicationContext
{
    private static readonly System.Text.Json.JsonSerializerOptions DiagnosticJsonOptions =
        new() { WriteIndented = true };
    private readonly ProtectedSettingsStore settingsStore = new();
    private readonly CanonicalFieldCatalog catalog = CanonicalFieldCatalog.Default;
    private readonly TabularDataParser parser;
    private readonly FocusedFieldMatcher matcher;
    private readonly TargetValueAdapter valueAdapter;
    private readonly PassengerSession session = new();
    private readonly GlobalHotkeyService hotkeys = new();
    private readonly UiAutomationInspector automationInspector = new();
    private readonly SessionTargetMappingStore targetMappings = new();
    private readonly PasteCommitGuard pasteCommitGuard = new();
    private readonly MainForm mainForm = new();
    private readonly NotifyIcon notifyIcon;
    private readonly ContextMenuStrip trayMenu = new();
    private readonly System.Windows.Forms.Timer inactivityTimer = new();
    private readonly CancellationTokenSource lifetime = new();
    private CancellationTokenSource sessionBoundary = new();
    private readonly List<SmartCopyPaste.Core.Diagnostics.SanitizedDiagnosticEvent> diagnosticEvents = [];
    private readonly byte[] userSecret;
    private readonly ToolStripMenuItem activePassengerMenu = new("Active Passenger");
    private readonly ToolStripMenuItem headerProfilesMenu = new("Header Profiles");
    private readonly ToolStripMenuItem nextPassengerItem = new("Next Passenger");
    private readonly ToolStripMenuItem previousPassengerItem = new("Previous Passenger");
    private readonly ToolStripMenuItem lockPassengerItem = new("Lock Passenger");
    private readonly ToolStripMenuItem pauseItem = new("Pause Smart Paste");
    private readonly ToolStripMenuItem startWithWindowsItem = new("Start with Windows");
    private readonly ToolStripMenuItem clearActiveItem = new("Clear Active Passenger");
    private readonly ToolStripMenuItem clearAllItem = new("Clear All Temporary Data");
    private readonly ToolStripMenuItem shortcutSettingsItem = new("Shortcut Settings");
    private PersistedAppSettings settings;
    private DateTimeOffset lastActivity = DateTimeOffset.UtcNow;
    private string hotkeyStatus = "Not registered";
    private string? lastErrorCode;
    private bool paused;
    private bool busy;
    private bool exiting;
    private bool cleanedUp;

    internal TrayApplicationContext(bool showMainWindow = false)
    {
        SettingsLoadResult loaded = settingsStore.Load();
        settings = loaded.Settings;
        userSecret = ProtectedSettingsStore.GetUserSecret(settings);
        parser = new TabularDataParser(catalog);
        matcher = new FocusedFieldMatcher(catalog);
        valueAdapter = new TargetValueAdapter(catalog);

        ConfigureMainForm();
        BuildTrayMenu();
        notifyIcon = new NotifyIcon
        {
            ContextMenuStrip = trayMenu,
            Icon = SystemIcons.Application,
            Text = "Smart COPY/PASTE - No passenger copied",
            Visible = true,
        };
        notifyIcon.DoubleClick += (_, _) => mainForm.ShowFromTray();

        hotkeys.CommandPressed += OnHotkeyPressed;
        RegisterConfiguredHotkeys();
        SystemEvents.SessionSwitch += OnSessionSwitch;

        inactivityTimer.Interval = 30_000;
        inactivityTimer.Tick += (_, _) => CheckInactivity();
        inactivityTimer.Start();

        _ = mainForm.Handle;
        RefreshUi();
        if (showMainWindow)
        {
            mainForm.ShowFromTray();
        }

        if (!string.IsNullOrWhiteSpace(loaded.Warning))
        {
            ShowNotification("Settings warning", loaded.Warning, ToolTipIcon.Warning);
        }
    }

    private void ConfigureMainForm()
    {
        mainForm.PreviousRequested += () => Navigate(previous: true);
        mainForm.NextRequested += () => Navigate(previous: false);
        mainForm.PauseRequested += TogglePause;
        mainForm.ClearActiveRequested += ClearActive;
        mainForm.ClearAllRequested += () => ClearAll("USER_CLEAR");
        mainForm.DiagnosticsRequested += ShowDiagnostics;
        mainForm.PassengerSelected += SelectPassenger;
        mainForm.LockChanged += SetPassengerLock;
        mainForm.StartWithWindowsChanged += SetStartWithWindows;
    }

    private void BuildTrayMenu()
    {
        AddMenuItem("Open Smart COPY/PASTE", (_, _) => mainForm.ShowFromTray());
        _ = trayMenu.Items.Add(new ToolStripSeparator());
        AddCommandMenuItem("Capture / Save Headers", HotkeyCommand.CaptureHeaders);
        AddCommandMenuItem("Smart Copy Passenger Rows", HotkeyCommand.SmartCopy);
        AddCommandMenuItem("Smart Paste", HotkeyCommand.SmartPaste);
        AddCommandMenuItem("Choose Field...", HotkeyCommand.OpenPicker);
        _ = trayMenu.Items.Add(headerProfilesMenu);
        _ = trayMenu.Items.Add(activePassengerMenu);
        nextPassengerItem.Click += (_, _) => Navigate(previous: false);
        previousPassengerItem.Click += (_, _) => Navigate(previous: true);
        lockPassengerItem.Click += (_, _) => SetPassengerLock(!session.Locked);
        pauseItem.Click += (_, _) => TogglePause();
        _ = trayMenu.Items.Add(nextPassengerItem);
        _ = trayMenu.Items.Add(previousPassengerItem);
        _ = trayMenu.Items.Add(lockPassengerItem);
        _ = trayMenu.Items.Add(pauseItem);
        _ = trayMenu.Items.Add(new ToolStripSeparator());
        clearActiveItem.Click += (_, _) => ClearActive();
        clearAllItem.Click += (_, _) => ClearAll("USER_CLEAR");
        shortcutSettingsItem.Click += (_, _) => ShowShortcutSettings();
        _ = trayMenu.Items.Add(clearActiveItem);
        _ = trayMenu.Items.Add(clearAllItem);
        _ = trayMenu.Items.Add(shortcutSettingsItem);
        startWithWindowsItem.CheckOnClick = false;
        startWithWindowsItem.Click += (_, _) => SetStartWithWindows(!settings.StartWithWindows);
        _ = trayMenu.Items.Add(startWithWindowsItem);
        AddMenuItem("Diagnostics", (_, _) => ShowDiagnostics());
        AddMenuItem("About", (_, _) => ShowAbout());
        _ = trayMenu.Items.Add(new ToolStripSeparator());
        AddMenuItem("Exit", (_, _) => ExitExplicitly());
    }

    private void AddMenuItem(string text, EventHandler handler) =>
        _ = trayMenu.Items.Add(text, null, handler);

    private void AddCommandMenuItem(string text, HotkeyCommand command) =>
        AddMenuItem(text, (_, _) => BeginCommand(command));

    private void RegisterConfiguredHotkeys()
    {
        IReadOnlyList<string> failures = hotkeys.Register(settings.Hotkeys);
        hotkeyStatus = failures.Count == 0
            ? "All 8 shortcuts registered"
            : $"{failures.Count} shortcut(s) unavailable";
        if (failures.Count > 0)
        {
            lastErrorCode = "HOTKEY_REGISTRATION_FAILED";
            ShowNotification(
                "Shortcut warning",
                "One or more shortcuts are already used. Open Shortcut Settings.",
                ToolTipIcon.Warning);
        }
    }

    private async void OnHotkeyPressed(object? sender, HotkeyCommand command) =>
        await HandleCommandSafelyAsync(command).ConfigureAwait(true);

    private void BeginCommand(HotkeyCommand command) =>
        _ = HandleCommandSafelyAsync(command);

    private async Task HandleCommandSafelyAsync(HotkeyCommand command)
    {
        TouchActivity();
        if (busy && command is not HotkeyCommand.PauseResume)
        {
            System.Media.SystemSounds.Beep.Play();
            return;
        }

        bool ownsBusyState = command is
            HotkeyCommand.CaptureHeaders or
            HotkeyCommand.SmartCopy or
            HotkeyCommand.SmartPaste or
            HotkeyCommand.OpenPicker;
        CancellationTokenSource? commandCancellation = null;
        try
        {
            if (ownsBusyState)
            {
                busy = true;
                RefreshUi();
            }

            switch (command)
            {
                case HotkeyCommand.PauseResume:
                    TogglePause();
                    break;
                case HotkeyCommand.NextPassenger:
                    Navigate(previous: false);
                    break;
                case HotkeyCommand.PreviousPassenger:
                    Navigate(previous: true);
                    break;
                case HotkeyCommand.ClearActivePassenger:
                    ClearActive();
                    break;
                default:
                    commandCancellation = CancellationTokenSource.CreateLinkedTokenSource(
                        lifetime.Token,
                        sessionBoundary.Token);
                    await ExecuteWorkflowCommandAsync(
                        command,
                        commandCancellation.Token).ConfigureAwait(true);
                    break;
            }
        }
        catch (OperationCanceledException) when (
            lifetime.IsCancellationRequested ||
            commandCancellation?.IsCancellationRequested == true)
        {
        }
        catch (Exception exception)
        {
            lastErrorCode = $"APP_{exception.GetType().Name.ToUpperInvariant()}";
            AddDiagnostic(lastErrorCode, "runtime", SmartCopyPaste.Core.Diagnostics.DiagnosticSeverity.Error);
            ShowNotification(
                "Smart COPY/PASTE could not complete the action",
                exception is InvalidOperationException or InvalidDataException
                    ? exception.Message
                    : "Try again. Open Diagnostics if the problem continues.",
                ToolTipIcon.Error);
        }
        finally
        {
            commandCancellation?.Dispose();
            if (ownsBusyState)
            {
                busy = false;
            }

            RefreshUi();
        }
    }

    private void Navigate(bool previous)
    {
        if (RejectPassengerMutationWhileBusy())
        {
            return;
        }

        SessionMutationResult result = previous ? session.Previous() : session.Next();
        if (result.Status == SessionMutationStatus.Locked)
        {
            ShowNotification("Passenger locked", "Unlock the active passenger before switching.", ToolTipIcon.Warning);
        }
        else if (result.Changed && result.Active is not null)
        {
            ShowNotification(
                "Active passenger changed",
                $"Passenger {result.ActiveIndex + 1} of {session.Profiles.Count} is now active.",
                ToolTipIcon.Info);
        }

        TouchActivity();
        RefreshUi();
    }

    private void SelectPassenger(Guid profileId)
    {
        if (RejectPassengerMutationWhileBusy())
        {
            return;
        }

        SessionMutationResult result = session.Select(profileId);
        if (result.Status == SessionMutationStatus.Locked)
        {
            ShowNotification("Passenger locked", "Unlock the active passenger before switching.", ToolTipIcon.Warning);
        }

        TouchActivity();
        RefreshUi();
    }

    private void SetPassengerLock(bool locked)
    {
        if (RejectPassengerMutationWhileBusy())
        {
            return;
        }

        if (locked)
        {
            CancelPendingSessionOperations();
        }

        session.Locked = locked;
        ShowNotification(
            locked ? "Passenger locked" : "Passenger unlocked",
            locked ? "Passenger switching is disabled." : "Passenger switching is available.",
            ToolTipIcon.Info);
        TouchActivity();
        RefreshUi();
    }

    private void ClearActive()
    {
        if (RejectPassengerMutationWhileBusy())
        {
            return;
        }

        _ = session.ClearActive();
        if (session.Profiles.Count == 0)
        {
            targetMappings.Clear();
        }

        AddDiagnostic("ACTIVE_PASSENGER_CLEARED", "session");
        ShowNotification("Passenger cleared", "The active passenger was removed from memory.", ToolTipIcon.Info);
        TouchActivity();
        RefreshUi();
    }

    private void ClearAll(string reasonCode)
    {
        if (string.Equals(reasonCode, "USER_CLEAR", StringComparison.Ordinal) &&
            RejectPassengerMutationWhileBusy())
        {
            return;
        }

        CancelPendingSessionOperations();
        _ = session.Clear();
        targetMappings.Clear();
        AddDiagnostic(reasonCode, "session");
        ShowNotification("Temporary data cleared", "No passenger values remain active.", ToolTipIcon.Info);
        RefreshUi();
    }

    private bool RejectPassengerMutationWhileBusy()
    {
        if (!busy)
        {
            return false;
        }

        System.Media.SystemSounds.Beep.Play();
        return true;
    }

    private void TogglePause()
    {
        paused = !paused;
        if (paused)
        {
            CancelPendingSessionOperations();
        }

        ShowNotification(
            paused ? "Smart Paste paused" : "Smart Paste resumed",
            paused ? "Passenger data remains in memory until cleared or timed out." : "Smart Paste is ready.",
            ToolTipIcon.Info);
        TouchActivity();
        RefreshUi();
    }

    private void SetStartWithWindows(bool enabled)
    {
        if (!StartupRegistrationService.TrySetEnabled(enabled))
        {
            ShowNotification(
                "Startup setting unchanged",
                "Windows did not allow the startup setting to be changed.",
                ToolTipIcon.Warning);
            RefreshUi();
            return;
        }

        settings.StartWithWindows = enabled;
        SaveSettings();
        RefreshUi();
    }

    private void CheckInactivity()
    {
        if (session.Profiles.Count == 0)
        {
            return;
        }

        if (DateTimeOffset.UtcNow - lastActivity >= TimeSpan.FromMinutes(settings.InactivityMinutes))
        {
            ClearAll("INACTIVITY_TIMEOUT");
        }
    }

    private void TouchActivity() => lastActivity = DateTimeOffset.UtcNow;

    private void CancelPendingSessionOperations()
    {
        CancellationTokenSource previousBoundary = sessionBoundary;
        sessionBoundary = new CancellationTokenSource();
        previousBoundary.Cancel();
        pasteCommitGuard.Invalidate();
        previousBoundary.Dispose();
    }

    private void RefreshUi()
    {
        PassengerProfile? active = session.Active;
        notifyIcon.Text = paused
            ? "Smart COPY/PASTE - Paused"
            : active is null
                ? "Smart COPY/PASTE - No passenger copied"
                : "Smart COPY/PASTE - Ready";
        pauseItem.Text = paused ? "Resume Smart Paste" : "Pause Smart Paste";
        lockPassengerItem.Text = session.Locked ? "Unlock Passenger" : "Lock Passenger";
        activePassengerMenu.Enabled = !busy;
        headerProfilesMenu.Enabled = !busy;
        lockPassengerItem.Enabled = !busy && active is not null;
        nextPassengerItem.Enabled =
            !busy &&
            active is not null &&
            !session.Locked &&
            session.ActiveIndex < session.Profiles.Count - 1;
        previousPassengerItem.Enabled =
            !busy && active is not null && !session.Locked && session.ActiveIndex > 0;
        clearActiveItem.Enabled = !busy && active is not null;
        clearAllItem.Enabled = !busy && active is not null;
        shortcutSettingsItem.Enabled = !busy;
        startWithWindowsItem.Checked = settings.StartWithWindows;
        RebuildPassengerMenu();
        RebuildHeaderProfilesMenu();
        mainForm.UpdateState(session, paused, settings.StartWithWindows, busy);
    }

    private void RebuildPassengerMenu()
    {
        activePassengerMenu.DropDownItems.Clear();
        if (session.Profiles.Count == 0)
        {
            _ = activePassengerMenu.DropDownItems.Add("(none)");
            activePassengerMenu.DropDownItems[0].Enabled = false;
            return;
        }

        foreach (PassengerProfile profile in session.Profiles)
        {
            var item = new ToolStripMenuItem(profile.DisplayName)
            {
                Checked = session.Active?.ProfileId == profile.ProfileId,
                Tag = profile.ProfileId,
            };
            item.Click += (_, _) =>
            {
                if (item.Tag is Guid profileId)
                {
                    SelectPassenger(profileId);
                }
            };
            _ = activePassengerMenu.DropDownItems.Add(item);
        }
    }

    private void RebuildHeaderProfilesMenu()
    {
        headerProfilesMenu.DropDownItems.Clear();
        if (settings.HeaderTemplates.Count == 0)
        {
            _ = headerProfilesMenu.DropDownItems.Add("(capture headers first)");
            headerProfilesMenu.DropDownItems[0].Enabled = false;
            return;
        }

        foreach (HeaderTemplateRecord template in settings.HeaderTemplates)
        {
            var item = new ToolStripMenuItem(template.DisplayName)
            {
                Checked = string.Equals(
                    settings.ActiveFallbackTemplateId,
                    template.TemplateId,
                    StringComparison.Ordinal),
                Tag = template.TemplateId,
            };
            item.Click += (_, _) =>
            {
                settings.ActiveFallbackTemplateId = item.Tag as string;
                SaveSettings();
                RefreshUi();
            };
            _ = headerProfilesMenu.DropDownItems.Add(item);
        }
    }

    private void ShowShortcutSettings()
    {
        if (RejectPassengerMutationWhileBusy())
        {
            return;
        }

        hotkeys.UnregisterAll();
        Dictionary<HotkeyCommand, HotkeySetting> previous = HotkeySettingsAdapter.Clone(settings.Hotkeys);
        using var form = new ShortcutSettingsForm(previous);
        if (form.ShowDialog(mainForm.Visible ? mainForm : null) != DialogResult.OK)
        {
            _ = hotkeys.Register(previous);
            return;
        }

        Dictionary<HotkeyCommand, HotkeySetting> candidate = form.Result;
        IReadOnlyList<string> failures = hotkeys.Register(candidate);
        if (failures.Count > 0)
        {
            _ = hotkeys.Register(previous);
            ShowNotification(
                "Shortcuts not changed",
                "A selected shortcut is already in use by Windows or another application.",
                ToolTipIcon.Warning);
            return;
        }

        settings.Hotkeys = candidate;
        hotkeyStatus = "All 8 shortcuts registered";
        SaveSettings();
        RefreshUi();
    }

    private void ShowDiagnostics()
    {
        string report = BuildSanitizedDiagnosticReport();
        using var form = new DiagnosticsForm(report);
        _ = form.ShowDialog(mainForm.Visible ? mainForm : null);
    }

    private static void ShowAbout() =>
        MessageBox.Show(
            $"Smart COPY/PASTE {Application.ProductVersion}\n\nLocal-only deterministic assistance for standard Chrome, Edge, and Brave fields.\nNo AI, cloud service, or browser extension is used.",
            "About Smart COPY/PASTE",
            MessageBoxButtons.OK,
            MessageBoxIcon.Information);

    private void OnSessionSwitch(object sender, SessionSwitchEventArgs eventArgs)
    {
        if (eventArgs.Reason is not (
            SessionSwitchReason.SessionLock or
            SessionSwitchReason.SessionLogoff or
            SessionSwitchReason.RemoteDisconnect))
        {
            return;
        }

        if (mainForm.IsHandleCreated)
        {
            try
            {
                mainForm.BeginInvoke(() => ClearAll("WINDOWS_SESSION_CLEARED"));
            }
            catch (ObjectDisposedException)
            {
            }
            catch (InvalidOperationException)
            {
            }
        }
    }

    private void SaveSettings()
    {
        try
        {
            settingsStore.Save(settings);
        }
        catch (IOException)
        {
            lastErrorCode = "SETTINGS_SAVE_FAILED";
        }
        catch (UnauthorizedAccessException)
        {
            lastErrorCode = "SETTINGS_SAVE_DENIED";
        }
        catch (InvalidDataException)
        {
            lastErrorCode = "SETTINGS_VALIDATION_FAILED";
        }
    }

    private void ShowNotification(string title, string text, ToolTipIcon icon)
    {
        notifyIcon.BalloonTipTitle = title;
        notifyIcon.BalloonTipText = text;
        notifyIcon.BalloonTipIcon = icon;
        notifyIcon.ShowBalloonTip(3000);
    }

    private void AddDiagnostic(
        string code,
        string component,
        SmartCopyPaste.Core.Diagnostics.DiagnosticSeverity severity =
            SmartCopyPaste.Core.Diagnostics.DiagnosticSeverity.Information)
    {
        diagnosticEvents.Add(
            SmartCopyPaste.Core.Diagnostics.SanitizedDiagnosticEvent.Create(
                DateTimeOffset.UtcNow,
                code,
                component,
                severity));
        if (diagnosticEvents.Count > 100)
        {
            diagnosticEvents.RemoveAt(0);
        }
    }

    private string BuildSanitizedDiagnosticReport()
    {
        var snapshot = new SmartCopyPaste.Core.Diagnostics.SanitizedDiagnosticSnapshot(
            Application.ProductVersion,
            catalog.Version,
            settings.SchemaVersion,
            settings.HeaderTemplates.Count,
            session.Profiles.Count,
            paused,
            hotkeyStatus,
            lastErrorCode);
        SmartCopyPaste.Core.Diagnostics.SanitizedDiagnosticReport report =
            SmartCopyPaste.Core.Diagnostics.SanitizedDiagnosticReport.Create(snapshot, diagnosticEvents);
        return System.Text.Json.JsonSerializer.Serialize(report, DiagnosticJsonOptions);
    }

    private void ExitExplicitly()
    {
        exiting = true;
        ExitThread();
    }

    protected override void ExitThreadCore()
    {
        if (!exiting)
        {
            return;
        }

        Cleanup();
        base.ExitThreadCore();
    }

    private void Cleanup()
    {
        if (cleanedUp)
        {
            return;
        }

        cleanedUp = true;
        lifetime.Cancel();
        sessionBoundary.Cancel();
        pasteCommitGuard.Invalidate();
        inactivityTimer.Stop();
        _ = session.Clear();
        targetMappings.Clear();
        SaveSettings();
        SystemEvents.SessionSwitch -= OnSessionSwitch;
        hotkeys.CommandPressed -= OnHotkeyPressed;
        hotkeys.Dispose();
        automationInspector.Dispose();
        notifyIcon.Visible = false;
        notifyIcon.Dispose();
        trayMenu.Dispose();
        mainForm.Dispose();
        inactivityTimer.Dispose();
        lifetime.Dispose();
        sessionBoundary.Dispose();
        Array.Clear(userSecret);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            Cleanup();
        }

        base.Dispose(disposing);
    }
}
