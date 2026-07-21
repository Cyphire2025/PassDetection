using SmartCopyPaste.Core.Catalog;
using SmartCopyPaste.Core.Security;
using SmartCopyPaste.Core.Session;
using SmartCopyPaste.App.Services;

namespace SmartCopyPaste.App.Forms;

internal sealed class MainForm : Form
{
    private readonly CanonicalFieldCatalog catalog = CanonicalFieldCatalog.Default;
    private readonly Label statusLabel = new();
    private readonly ComboBox passengerSelector = new();
    private readonly CheckBox lockPassenger = new();
    private readonly CheckBox revealValues = new();
    private readonly CheckBox startWithWindows = new();
    private readonly Button previousButton = CreateButton("Previous", 100);
    private readonly Button nextButton = CreateButton("Next", 80);
    private readonly Button pauseButton = CreateButton("Pause Smart Paste", 160);
    private readonly Button clearActiveButton = CreateButton("Clear Active", 110);
    private readonly Button clearAllButton = CreateButton("Clear All", 90);
    private readonly DataGridView fieldsGrid = new();
    private readonly Font baseUiFont =
        new("Segoe UI", 10.5F, FontStyle.Regular, GraphicsUnit.Point);
    private readonly Font headingFont =
        new("Segoe UI", 20F, FontStyle.Bold, GraphicsUnit.Point);
    private readonly Font statusFont =
        new("Segoe UI", 11F, FontStyle.Regular, GraphicsUnit.Point);
    private PassengerSession? currentSession;
    private bool updating;

    internal MainForm()
    {
        Font = baseUiFont;
        Text = "Smart COPY/PASTE";
        AccessibleName = "Smart COPY/PASTE passenger session";
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96F, 96F);
        MinimumSize = new Size(780, 560);
        Size = new Size(1040, 720);
        ShowInTaskbar = true;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Padding = new Padding(22),
            ColumnCount = 1,
            RowCount = 6,
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        Controls.Add(root);

        root.Controls.Add(new Label
        {
            Text = "Smart COPY/PASTE",
            AutoSize = true,
            Font = headingFont,
            Margin = new Padding(0, 0, 0, 4),
            AccessibleName = "Smart COPY/PASTE",
        });

        statusLabel.AutoSize = true;
        statusLabel.Dock = DockStyle.Fill;
        statusLabel.Text = "No passenger copied. Select headers in Excel and press Ctrl+Alt+H.";
        statusLabel.Font = statusFont;
        statusLabel.Margin = new Padding(0, 0, 0, 14);
        statusLabel.AccessibleName = "Application status";
        statusLabel.AccessibleRole = AccessibleRole.StaticText;
        root.Controls.Add(statusLabel);

        root.Controls.Add(CreatePassengerPanel());

        ConfigureFieldsGrid();
        root.Controls.Add(fieldsGrid);

        root.Controls.Add(CreateOptionsPanel());
        root.Controls.Add(CreateActionPanel());

        Shown += (_, _) =>
        {
            ApplyDpiMetrics();
            ResponsiveWindowLayout.ClampToWorkingArea(
                this,
                new Size(780, 560));
        };
        DpiChanged += (_, _) =>
        {
            ApplyDpiMetrics();
            ResponsiveWindowLayout.ClampToWorkingArea(
                this,
                new Size(780, 560));
        };
    }

    internal event Action? PreviousRequested;

    internal event Action? NextRequested;

    internal event Action? PauseRequested;

    internal event Action? ClearActiveRequested;

    internal event Action? ClearAllRequested;

    internal event Action? DiagnosticsRequested;

    internal event Action<Guid>? PassengerSelected;

    internal event Action<bool>? LockChanged;

    internal event Action<bool>? StartWithWindowsChanged;

    internal void UpdateState(
        PassengerSession session,
        bool paused,
        bool startsWithWindows,
        bool commandInProgress)
    {
        ArgumentNullException.ThrowIfNull(session);
        currentSession = session;
        updating = true;
        try
        {
            PassengerProfile? active = session.Active;
            statusLabel.Text = commandInProgress
                ? "Working… Passenger switching is temporarily disabled."
                : paused
                    ? active is null
                        ? "Smart Paste is paused. No passenger is currently copied."
                        : $"Smart Paste is paused — {active.DisplayName} • passenger {session.ActiveIndex + 1} of {session.Profiles.Count}"
                : active is null
                    ? "No passenger copied. Select headers in Excel and press Ctrl+Alt+H."
                    : $"Ready — {active.DisplayName} • passenger {session.ActiveIndex + 1} of {session.Profiles.Count}";
            statusLabel.ForeColor = paused
                ? SystemColors.GrayText
                : SystemColors.WindowText;

            passengerSelector.BeginUpdate();
            passengerSelector.Items.Clear();
            foreach (PassengerProfile profile in session.Profiles)
            {
                passengerSelector.Items.Add(new ProfileChoice(profile.ProfileId, profile.DisplayName));
            }

            if (active is not null)
            {
                passengerSelector.SelectedIndex = session.Profiles
                    .Select(static profile => profile.ProfileId)
                    .ToList()
                    .IndexOf(active.ProfileId);
            }
            else
            {
                passengerSelector.SelectedIndex = -1;
            }

            passengerSelector.EndUpdate();
            lockPassenger.Checked = session.Locked;
            startWithWindows.Checked = startsWithWindows;
            pauseButton.Text = paused ? "Resume Smart Paste" : "Pause Smart Paste";
            passengerSelector.Enabled =
                !commandInProgress && active is not null && !session.Locked;
            lockPassenger.Enabled = !commandInProgress && active is not null;
            previousButton.Enabled =
                !commandInProgress &&
                active is not null &&
                !session.Locked &&
                session.ActiveIndex > 0;
            nextButton.Enabled =
                !commandInProgress &&
                active is not null &&
                !session.Locked &&
                session.ActiveIndex < session.Profiles.Count - 1;
            clearActiveButton.Enabled = !commandInProgress && active is not null;
            clearAllButton.Enabled = !commandInProgress && active is not null;
        }
        finally
        {
            updating = false;
        }

        RefreshFields();
    }

    internal void ShowFromTray()
    {
        if (!Visible)
        {
            Show();
        }

        if (WindowState == FormWindowState.Minimized)
        {
            WindowState = FormWindowState.Normal;
        }

        ShowInTaskbar = true;
        Activate();
    }

    protected override void OnFormClosing(FormClosingEventArgs eventArgs)
    {
        if (eventArgs.CloseReason == CloseReason.UserClosing)
        {
            eventArgs.Cancel = true;
            revealValues.Checked = false;
            Hide();
            ShowInTaskbar = false;
        }

        base.OnFormClosing(eventArgs);
    }

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        if (disposing)
        {
            baseUiFont.Dispose();
            headingFont.Dispose();
            statusFont.Dispose();
        }
    }

    private GroupBox CreatePassengerPanel()
    {
        var group = new GroupBox
        {
            Text = "Passenger session",
            Dock = DockStyle.Fill,
            AutoSize = true,
            Padding = new Padding(12, 10, 12, 12),
            Margin = new Padding(0, 0, 0, 14),
        };
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            ColumnCount = 5,
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        layout.Controls.Add(new Label
        {
            Text = "Active passenger",
            AutoSize = true,
            Anchor = AnchorStyles.Left,
            Margin = new Padding(0, 7, 10, 0),
        });

        passengerSelector.DropDownStyle = ComboBoxStyle.DropDownList;
        passengerSelector.Dock = DockStyle.Fill;
        passengerSelector.MinimumSize = new Size(220, 34);
        passengerSelector.Margin = new Padding(0, 2, 10, 2);
        passengerSelector.AccessibleName = "Active passenger";
        passengerSelector.SelectedIndexChanged += (_, _) => SelectPassenger();
        layout.Controls.Add(passengerSelector);

        previousButton.Click += (_, _) => PreviousRequested?.Invoke();
        nextButton.Click += (_, _) => NextRequested?.Invoke();
        layout.Controls.Add(previousButton);
        layout.Controls.Add(nextButton);

        lockPassenger.Text = "Lock passenger";
        lockPassenger.AutoSize = true;
        lockPassenger.Anchor = AnchorStyles.Left;
        lockPassenger.Margin = new Padding(12, 7, 0, 0);
        lockPassenger.AccessibleDescription =
            "Prevents accidental passenger switching until unlocked.";
        lockPassenger.CheckedChanged += (_, _) =>
        {
            if (!updating)
            {
                LockChanged?.Invoke(lockPassenger.Checked);
            }
        };
        layout.Controls.Add(lockPassenger);
        group.Controls.Add(layout);
        return group;
    }

    private FlowLayoutPanel CreateOptionsPanel()
    {
        var options = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            WrapContents = true,
            Margin = new Padding(0, 12, 0, 4),
        };
        revealValues.Text = "Reveal passenger values";
        revealValues.AutoSize = true;
        revealValues.Margin = new Padding(0, 7, 20, 0);
        revealValues.AccessibleDescription =
            "Shows full passenger values on screen until hidden or the window closes.";
        revealValues.CheckedChanged += (_, _) => RefreshFields();
        options.Controls.Add(revealValues);

        startWithWindows.Text = "Start with Windows";
        startWithWindows.AutoSize = true;
        startWithWindows.Margin = new Padding(0, 7, 0, 0);
        startWithWindows.CheckedChanged += (_, _) =>
        {
            if (!updating)
            {
                StartWithWindowsChanged?.Invoke(startWithWindows.Checked);
            }
        };
        options.Controls.Add(startWithWindows);
        return options;
    }

    private FlowLayoutPanel CreateActionPanel()
    {
        var actions = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            WrapContents = true,
            Margin = new Padding(0, 6, 0, 0),
        };
        pauseButton.Click += (_, _) => PauseRequested?.Invoke();
        clearActiveButton.Click += (_, _) => ClearActiveRequested?.Invoke();
        clearAllButton.Click += (_, _) => ClearAllRequested?.Invoke();
        Button diagnostics = CreateButton("Diagnostics", 110);
        diagnostics.Click += (_, _) => DiagnosticsRequested?.Invoke();
        actions.Controls.Add(pauseButton);
        actions.Controls.Add(clearActiveButton);
        actions.Controls.Add(clearAllButton);
        actions.Controls.Add(diagnostics);
        return actions;
    }

    private void ConfigureFieldsGrid()
    {
        fieldsGrid.Dock = DockStyle.Fill;
        fieldsGrid.ReadOnly = true;
        fieldsGrid.AllowUserToAddRows = false;
        fieldsGrid.AllowUserToDeleteRows = false;
        fieldsGrid.AllowUserToResizeRows = false;
        fieldsGrid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill;
        fieldsGrid.RowHeadersVisible = false;
        fieldsGrid.SelectionMode = DataGridViewSelectionMode.FullRowSelect;
        fieldsGrid.MultiSelect = false;
        fieldsGrid.BackgroundColor = SystemColors.Window;
        fieldsGrid.BorderStyle = BorderStyle.FixedSingle;
        fieldsGrid.ColumnHeadersHeight = 38;
        fieldsGrid.ColumnHeadersHeightSizeMode =
            DataGridViewColumnHeadersHeightSizeMode.DisableResizing;
        fieldsGrid.RowTemplate.Height = 34;
        fieldsGrid.AccessibleName = "Copied passenger fields";
        fieldsGrid.Columns.AddRange(
            new DataGridViewTextBoxColumn
            {
                Name = "field",
                HeaderText = "Passenger field",
                FillWeight = 42,
                MinimumWidth = 220,
            },
            new DataGridViewTextBoxColumn
            {
                Name = "value",
                HeaderText = "Value",
                FillWeight = 58,
                MinimumWidth = 260,
            });
    }

    private void RefreshFields()
    {
        fieldsGrid.Rows.Clear();
        PassengerProfile? active = currentSession?.Active;
        if (active is null)
        {
            return;
        }

        foreach ((string fieldId, string value) in active.Fields
            .OrderBy(static pair => pair.Key, StringComparer.Ordinal))
        {
            string displayName = catalog.TryGetDefinition(
                fieldId,
                out CanonicalFieldDefinition? definition) && definition is not null
                    ? definition.DisplayName
                    : fieldId;
            string visibleValue = revealValues.Checked
                ? value
                : SensitiveDataMasker.Mask(fieldId, value);
            _ = fieldsGrid.Rows.Add(displayName, visibleValue);
        }
    }

    private void ApplyDpiMetrics()
    {
        fieldsGrid.ColumnHeadersHeight =
            ResponsiveWindowLayout.ScaleMetric(38, DeviceDpi);
        fieldsGrid.RowTemplate.Height =
            ResponsiveWindowLayout.ScaleMetric(34, DeviceDpi);
        foreach (DataGridViewRow row in fieldsGrid.Rows)
        {
            row.Height = fieldsGrid.RowTemplate.Height;
        }
    }

    private void SelectPassenger()
    {
        if (!updating && passengerSelector.SelectedItem is ProfileChoice choice)
        {
            PassengerSelected?.Invoke(choice.Id);
        }
    }

    private static Button CreateButton(string text, int minimumWidth) =>
        new()
        {
            Text = text,
            AutoSize = true,
            MinimumSize = new Size(minimumWidth, 40),
            Margin = new Padding(0, 0, 8, 0),
        };

    private sealed record ProfileChoice(Guid Id, string Name)
    {
        public override string ToString() => Name;
    }
}
