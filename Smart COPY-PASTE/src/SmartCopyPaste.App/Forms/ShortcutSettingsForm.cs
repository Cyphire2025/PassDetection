using SmartCopyPaste.App.Models;
using SmartCopyPaste.App.Services;
using SmartCopyPaste.Core.Configuration;
using AppHotkeyModifiers = SmartCopyPaste.App.Models.HotkeyModifiers;

namespace SmartCopyPaste.App.Forms;

internal sealed class ShortcutSettingsForm : Form
{
    private readonly Dictionary<HotkeyCommand, HotkeySetting> workingCopy;
    private readonly Dictionary<HotkeyCommand, TextBox> editors = [];
    private readonly Font baseUiFont =
        new("Segoe UI", 10.5F, FontStyle.Regular, GraphicsUnit.Point);
    private readonly Font headingFont =
        new("Segoe UI", 16F, FontStyle.Bold, GraphicsUnit.Point);

    internal ShortcutSettingsForm(
        IReadOnlyDictionary<HotkeyCommand, HotkeySetting> current)
    {
        ArgumentNullException.ThrowIfNull(current);
        workingCopy = HotkeySettingsAdapter.Clone(current);

        Font = baseUiFont;
        Text = "Shortcut Settings";
        AccessibleName = "Smart COPY/PASTE shortcut settings";
        StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.Sizable;
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96F, 96F);
        MinimizeBox = false;
        MaximizeBox = false;
        ShowInTaskbar = false;
        Size = new Size(760, 620);
        MinimumSize = new Size(700, 520);
        KeyPreview = true;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Padding = new Padding(20),
            ColumnCount = 1,
            RowCount = 5,
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        Controls.Add(root);

        root.Controls.Add(new Label
        {
            Text = "Keyboard shortcuts",
            AutoSize = true,
            Font = headingFont,
            Margin = new Padding(0, 0, 0, 4),
            AccessibleRole = AccessibleRole.StaticText,
        });
        root.Controls.Add(new Label
        {
            Text = "Focus a shortcut box, then press the complete key combination. Use two modifiers, such as Ctrl+Alt.",
            AutoSize = true,
            Dock = DockStyle.Fill,
            ForeColor = SystemColors.GrayText,
            Margin = new Padding(0, 0, 0, 12),
            AccessibleRole = AccessibleRole.StaticText,
        });

        var editorTable = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            ColumnCount = 2,
            RowCount = workingCopy.Count,
            Margin = Padding.Empty,
        };
        editorTable.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 58));
        editorTable.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 42));
        root.Controls.Add(editorTable);

        int row = 0;
        foreach ((HotkeyCommand command, HotkeySetting setting) in
            workingCopy.OrderBy(static pair => pair.Key))
        {
            editorTable.RowStyles.Add(new RowStyle(SizeType.Percent, 100F / workingCopy.Count));
            string commandLabel = GetCommandLabel(command);
            editorTable.Controls.Add(new Label
            {
                Text = commandLabel,
                AutoEllipsis = true,
                Dock = DockStyle.Fill,
                TextAlign = ContentAlignment.MiddleLeft,
                Margin = new Padding(0, 3, 12, 3),
                AccessibleRole = AccessibleRole.StaticText,
            }, 0, row);

            var editor = new TextBox
            {
                ReadOnly = true,
                ShortcutsEnabled = false,
                Dock = DockStyle.Fill,
                Text = HotkeySettingsAdapter.Format(
                    setting.Modifiers,
                    setting.VirtualKey),
                Tag = command,
                Margin = new Padding(0, 5, 0, 5),
                MinimumSize = new Size(180, 34),
                AccessibleName = $"{commandLabel} shortcut",
                AccessibleDescription =
                    "Press a complete shortcut combination to replace this setting.",
            };
            editor.KeyDown += CaptureShortcut;
            editors.Add(command, editor);
            editorTable.Controls.Add(editor, 1, row);
            row++;
        }

        root.Controls.Add(new Label
        {
            Text = "Every shortcut must be unique and use at least two of Ctrl, Alt, and Shift. This prevents routine typing or navigation from triggering a global action.",
            AutoSize = true,
            Dock = DockStyle.Fill,
            ForeColor = SystemColors.GrayText,
            Margin = new Padding(0, 12, 0, 8),
            AccessibleRole = AccessibleRole.StaticText,
        });

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            FlowDirection = FlowDirection.RightToLeft,
            WrapContents = false,
            Margin = new Padding(0, 6, 0, 0),
        };
        Button cancel = new()
        {
            Text = "Cancel",
            AutoSize = true,
            MinimumSize = new Size(100, 40),
            DialogResult = DialogResult.Cancel,
        };
        Button save = new()
        {
            Text = "Apply shortcuts",
            AutoSize = true,
            MinimumSize = new Size(150, 40),
        };
        save.Click += (_, _) => ValidateAndClose();
        buttons.Controls.Add(cancel);
        buttons.Controls.Add(save);
        root.Controls.Add(buttons);
        AcceptButton = save;
        CancelButton = cancel;

        Shown += (_, _) => ResponsiveWindowLayout.ClampToWorkingArea(
            this,
            new Size(700, 520));
        DpiChanged += (_, _) => ResponsiveWindowLayout.ClampToWorkingArea(
            this,
            new Size(700, 520));
    }

    internal Dictionary<HotkeyCommand, HotkeySetting> Result =>
        HotkeySettingsAdapter.Clone(workingCopy);

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        if (disposing)
        {
            baseUiFont.Dispose();
            headingFont.Dispose();
        }
    }

    private void CaptureShortcut(object? sender, KeyEventArgs eventArgs)
    {
        if (sender is not TextBox editor ||
            editor.Tag is not HotkeyCommand command)
        {
            return;
        }

        if (eventArgs.KeyCode is
            Keys.ControlKey or Keys.ShiftKey or Keys.Menu or
            Keys.LWin or Keys.RWin)
        {
            eventArgs.SuppressKeyPress = true;
            return;
        }

        AppHotkeyModifiers modifiers = AppHotkeyModifiers.None;
        if (eventArgs.Control)
        {
            modifiers |= AppHotkeyModifiers.Control;
        }

        if (eventArgs.Alt)
        {
            modifiers |= AppHotkeyModifiers.Alt;
        }

        if (eventArgs.Shift)
        {
            modifiers |= AppHotkeyModifiers.Shift;
        }

        workingCopy[command] = new HotkeySetting
        {
            Modifiers = modifiers,
            VirtualKey = (int)eventArgs.KeyCode,
            DisplayName = HotkeySettingsAdapter.Format(
                modifiers,
                (int)eventArgs.KeyCode),
        };
        editor.Text = workingCopy[command].DisplayName;
        eventArgs.SuppressKeyPress = true;
        eventArgs.Handled = true;
    }

    private void ValidateAndClose()
    {
        var candidate = new PersistedAppSettings
        {
            Hotkeys = Result,
            InactivityMinutes = 30,
        };
        SettingsValidationResult validation;
        try
        {
            validation = SettingsValidator.Validate(
                HotkeySettingsAdapter.ToCoreSettings(candidate));
        }
        catch (InvalidDataException exception)
        {
            ShowValidationError(exception.Message);
            return;
        }

        if (!validation.IsValid)
        {
            ShowValidationError(validation.Issues[0].Message);
            return;
        }

        DialogResult = DialogResult.OK;
        Close();
    }

    private void ShowValidationError(string message) =>
        MessageBox.Show(
            this,
            message,
            "Invalid shortcut",
            MessageBoxButtons.OK,
            MessageBoxIcon.Warning);

    private static string GetCommandLabel(HotkeyCommand command) =>
        command switch
        {
            HotkeyCommand.CaptureHeaders => "Capture / save headers",
            HotkeyCommand.SmartCopy => "Smart Copy passenger rows",
            HotkeyCommand.SmartPaste => "Smart Paste",
            HotkeyCommand.OpenPicker => "Open field picker",
            HotkeyCommand.NextPassenger => "Next passenger",
            HotkeyCommand.PreviousPassenger => "Previous passenger",
            HotkeyCommand.PauseResume => "Pause / resume",
            HotkeyCommand.ClearActivePassenger => "Clear active passenger",
            _ => command.ToString(),
        };
}
