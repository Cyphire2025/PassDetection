using SmartCopyPaste.App.Models;
using SmartCopyPaste.App.Services;
using SmartCopyPaste.Core.Catalog;
using SmartCopyPaste.Core.Matching;
using SmartCopyPaste.Core.Security;
using SmartCopyPaste.Core.Session;

namespace SmartCopyPaste.App.Forms;

internal sealed class ManualPickerForm : Form
{
    private readonly List<PickerItem> allItems;
    private readonly HashSet<string> recommendedFieldIds;
    private readonly TextBox searchBox = new();
    private readonly DataGridView resultsGrid = new();
    private readonly Label resultStatus = new();
    private readonly CheckBox showAllFields = new();
    private readonly CheckBox rememberChoice = new();
    private readonly Button pasteButton = new();
    private readonly Font baseUiFont =
        new("Segoe UI", 10.5F, FontStyle.Regular, GraphicsUnit.Point);
    private readonly Font targetCaptionFont =
        new("Segoe UI", 10.5F, FontStyle.Bold, GraphicsUnit.Point);
    private readonly Font targetValueFont =
        new("Segoe UI", 12F, FontStyle.Bold, GraphicsUnit.Point);
    private string baseResultStatus = string.Empty;
    private int cancellationRequested;

    internal ManualPickerForm(
        PassengerProfile profile,
        FocusedFieldSnapshot? focusedField,
        IReadOnlyDictionary<string, string>? sourceHeaders = null,
        FieldCandidateRankingResult? ranking = null,
        FocusedFieldContext? fieldContext = null,
        TargetValueAdapter? targetValueAdapter = null)
    {
        ArgumentNullException.ThrowIfNull(profile);
        CanonicalFieldCatalog catalog = CanonicalFieldCatalog.Default;
        TargetValueAdapter adapter =
            targetValueAdapter ?? new TargetValueAdapter(catalog);
        IReadOnlyList<RankedFieldCandidate> rankedCandidates =
            ranking?.Candidates ?? Array.Empty<RankedFieldCandidate>();
        recommendedFieldIds = rankedCandidates
            .Select(static candidate => candidate.CanonicalFieldId)
            .ToHashSet(StringComparer.Ordinal);
        Dictionary<string, int> rankedOrder = rankedCandidates
            .Select((candidate, index) => (candidate.CanonicalFieldId, index))
            .ToDictionary(static pair => pair.CanonicalFieldId, static pair => pair.index, StringComparer.Ordinal);

        allItems = profile.Fields
            .Select(pair =>
            {
                RankedFieldCandidate? candidate = rankedCandidates.FirstOrDefault(item =>
                    string.Equals(item.CanonicalFieldId, pair.Key, StringComparison.Ordinal));
                string displayName = candidate?.DisplayName ??
                    (catalog.TryGetDefinition(
                        pair.Key,
                        out CanonicalFieldDefinition? definition) && definition is not null
                        ? definition.DisplayName
                        : pair.Key);
                string sourceHeader = sourceHeaders is not null &&
                    sourceHeaders.TryGetValue(pair.Key, out string? header)
                        ? header
                        : string.Empty;
                TargetValueAdaptationResult? adaptation = fieldContext is null
                    ? null
                    : adapter.Adapt(pair.Key, pair.Value, fieldContext);
                string previewValue = adaptation?.IsSafeToPaste == true
                    ? adaptation.Value
                    : pair.Value;
                bool isSafeToPaste = adaptation?.IsSafeToPaste ?? true;
                string formatNote = adaptation?.Status switch
                {
                    TargetValueAdaptationStatus.Adapted =>
                        " - formatted for this field",
                    TargetValueAdaptationStatus.Ambiguous or
                    TargetValueAdaptationStatus.Invalid =>
                        " - target format needs manual review",
                    _ => string.Empty,
                };
                return new PickerItem(
                    pair.Key,
                    displayName,
                    sourceHeader,
                    SensitiveDataMasker.Mask(pair.Key, previewValue),
                    candidate is not null,
                    isSafeToPaste,
                    formatNote,
                    rankedOrder.GetValueOrDefault(pair.Key, int.MaxValue));
            })
            .OrderBy(static item => item.Rank)
            .ThenBy(static item => item.DisplayName, StringComparer.CurrentCultureIgnoreCase)
            .ToList();

        Font = baseUiFont;
        Text = "Choose passenger data";
        AccessibleName = "Choose passenger data to paste";
        StartPosition = FormStartPosition.Manual;
        FormBorderStyle = FormBorderStyle.Sizable;
        MinimizeBox = false;
        ShowInTaskbar = false;
        TopMost = true;
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96F, 96F);
        Size = new Size(820, 600);
        MinimumSize = new Size(700, 500);
        KeyPreview = true;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Padding = new Padding(20),
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

        root.Controls.Add(CreateTargetPanel(focusedField));

        searchBox.Dock = DockStyle.Fill;
        searchBox.MinimumSize = new Size(0, 34);
        searchBox.Margin = new Padding(0, 12, 0, 8);
        searchBox.PlaceholderText = "Search passenger fields or Excel headers";
        searchBox.AccessibleName = "Search copied passenger fields";
        searchBox.TextChanged += (_, _) => ApplyFilter();
        searchBox.KeyDown += OnSearchKeyDown;
        root.Controls.Add(searchBox);

        var resultBar = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            ColumnCount = 2,
            Margin = new Padding(0, 0, 0, 8),
        };
        resultBar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        resultBar.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        resultStatus.AutoSize = true;
        resultStatus.Dock = DockStyle.Fill;
        resultStatus.ForeColor = SystemColors.GrayText;
        resultStatus.AccessibleName = "Picker result status";
        resultBar.Controls.Add(resultStatus, 0, 0);
        showAllFields.Text = "Show all copied fields";
        showAllFields.AutoSize = true;
        showAllFields.Visible =
            recommendedFieldIds.Count > 0 &&
            recommendedFieldIds.Count < allItems.Count;
        showAllFields.AccessibleDescription =
            "Shows fields that were not recommended for the focused website control.";
        showAllFields.CheckedChanged += (_, _) => ApplyFilter();
        resultBar.Controls.Add(showAllFields, 1, 0);
        root.Controls.Add(resultBar);

        ConfigureResultsGrid();
        root.Controls.Add(resultsGrid);

        var options = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            WrapContents = true,
            Margin = new Padding(0, 10, 0, 4),
        };
        rememberChoice.Text = "Remember this choice for this browser window and app session";
        rememberChoice.AutoSize = true;
        bool canRememberChoice =
            focusedField is not null &&
            SessionTargetMappingStore.CreateSignature(focusedField) is not null;
        rememberChoice.Checked = canRememberChoice;
        rememberChoice.Enabled = canRememberChoice;
        rememberChoice.Visible = focusedField is not null;
        rememberChoice.Margin = new Padding(0, 0, 22, 4);
        rememberChoice.AccessibleDescription =
            "Reuses this field choice only for the same browser process, window, and exact accessibility label until temporary data is cleared or the app exits.";
        options.Controls.Add(rememberChoice);
        root.Controls.Add(options);

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            FlowDirection = FlowDirection.RightToLeft,
            WrapContents = false,
            Margin = new Padding(0, 8, 0, 0),
        };
        Button cancel = CreateActionButton("Cancel");
        cancel.DialogResult = DialogResult.Cancel;
        pasteButton.Text = "Paste selected value";
        pasteButton.AutoSize = true;
        pasteButton.MinimumSize = new Size(160, 40);
        pasteButton.Enabled = false;
        pasteButton.Click += (_, _) => AcceptSelection();
        buttons.Controls.Add(cancel);
        buttons.Controls.Add(pasteButton);
        root.Controls.Add(buttons);
        AcceptButton = pasteButton;
        CancelButton = cancel;

        ApplyFilter();
        Rectangle targetBounds =
            focusedField?.BoundingRectangle ?? Rectangle.Empty;
        PositionNearTarget(targetBounds);
        Shown += (_, _) =>
        {
            ApplyDpiMetrics();
            ResponsiveWindowLayout.ClampToWorkingArea(
                this,
                new Size(700, 500),
                targetBounds);
            searchBox.Focus();
        };
        DpiChanged += (_, _) =>
        {
            ApplyDpiMetrics();
            ResponsiveWindowLayout.ClampToWorkingArea(
                this,
                new Size(700, 500),
                targetBounds);
        };
    }

    internal string? SelectedFieldId { get; private set; }

    internal bool RememberChoice => rememberChoice.Checked;

    internal int VisibleResultCount => resultsGrid.Rows.Count;

    internal bool ShowingRecommendationsOnly =>
        recommendedFieldIds.Count > 0 &&
        !showAllFields.Checked;

    internal void SetSearchTextForSelfTest(string value) =>
        searchBox.Text = value;

    internal void RequestCancellation()
    {
        _ = Interlocked.Exchange(ref cancellationRequested, 1);
        if (IsDisposed || !IsHandleCreated)
        {
            return;
        }

        try
        {
            if (InvokeRequired)
            {
                _ = BeginInvoke(CancelOnUiThread);
            }
            else
            {
                CancelOnUiThread();
            }
        }
        catch (ObjectDisposedException)
        {
            // The owning lifecycle gate already disposed the completed modal.
        }
        catch (InvalidOperationException)
        {
            // The modal completed while the cancellation callback was queued.
        }
    }

    private TableLayoutPanel CreateTargetPanel(
        FocusedFieldSnapshot? focusedField)
    {
        string targetName = focusedField is null || string.IsNullOrWhiteSpace(focusedField.AccessibleName)
            ? "Website field label unavailable"
            : focusedField.AccessibleName;
        string section = focusedField is not null &&
            !string.IsNullOrWhiteSpace(focusedField.SectionHeading)
                ? $" • {focusedField.SectionHeading}"
                : string.Empty;
        var panel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            ColumnCount = 1,
            Padding = new Padding(12, 10, 12, 10),
            BackColor = SystemColors.ControlLight,
            AccessibleName = "Focused website field",
        };
        panel.Controls.Add(new Label
        {
            Text = "Focused website field",
            AutoSize = true,
            Font = targetCaptionFont,
            ForeColor = SystemColors.GrayText,
            Margin = Padding.Empty,
        });
        panel.Controls.Add(new Label
        {
            Text = targetName + section,
            AutoSize = true,
            Dock = DockStyle.Fill,
            Font = targetValueFont,
            Margin = new Padding(0, 4, 0, 0),
            AccessibleName = $"Focused website field: {targetName}",
        });
        return panel;
    }

    private void ConfigureResultsGrid()
    {
        resultsGrid.Dock = DockStyle.Fill;
        resultsGrid.ReadOnly = true;
        resultsGrid.AllowUserToAddRows = false;
        resultsGrid.AllowUserToDeleteRows = false;
        resultsGrid.AllowUserToResizeRows = false;
        resultsGrid.AllowUserToOrderColumns = false;
        resultsGrid.MultiSelect = false;
        resultsGrid.RowHeadersVisible = false;
        resultsGrid.SelectionMode = DataGridViewSelectionMode.FullRowSelect;
        resultsGrid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill;
        resultsGrid.ColumnHeadersHeight = 38;
        resultsGrid.ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.DisableResizing;
        resultsGrid.RowTemplate.Height = 34;
        resultsGrid.BackgroundColor = SystemColors.Window;
        resultsGrid.BorderStyle = BorderStyle.FixedSingle;
        resultsGrid.AccessibleName = "Passenger field choices";
        resultsGrid.TabIndex = 1;
        resultsGrid.Columns.AddRange(
            new DataGridViewTextBoxColumn
            {
                Name = "field",
                HeaderText = "Passenger field",
                FillWeight = 42,
                MinimumWidth = 210,
            },
            new DataGridViewTextBoxColumn
            {
                Name = "source",
                HeaderText = "Excel header",
                FillWeight = 28,
                MinimumWidth = 140,
            },
            new DataGridViewTextBoxColumn
            {
                Name = "preview",
                HeaderText = "Value preview",
                FillWeight = 30,
                MinimumWidth = 160,
            });
        resultsGrid.SelectionChanged += (_, _) => UpdateSelectionState();
        resultsGrid.CellDoubleClick += (_, eventArgs) =>
        {
            if (eventArgs.RowIndex >= 0)
            {
                AcceptSelection();
            }
        };
        resultsGrid.KeyDown += OnResultsKeyDown;
    }

    private static Button CreateActionButton(string text) =>
        new()
        {
            Text = text,
            AutoSize = true,
            MinimumSize = new Size(100, 40),
        };

    private void ApplyFilter()
    {
        string query = searchBox.Text.Trim();
        bool recommendationsOnly =
            recommendedFieldIds.Count > 0 &&
            !showAllFields.Checked;
        IEnumerable<PickerItem> visible = allItems.Where(item =>
            (!recommendationsOnly || item.IsRecommended) &&
            (query.Length == 0 ||
             item.DisplayName.Contains(query, StringComparison.CurrentCultureIgnoreCase) ||
             item.SourceHeader.Contains(query, StringComparison.CurrentCultureIgnoreCase) ||
             item.FieldId.Contains(query, StringComparison.OrdinalIgnoreCase)));

        resultsGrid.SuspendLayout();
        resultsGrid.Rows.Clear();
        foreach (PickerItem item in visible)
        {
            string fieldLabel = item.IsRecommended
                ? $"{item.DisplayName} - Recommended{item.FormatNote}"
                : item.DisplayName + item.FormatNote;
            int rowIndex = resultsGrid.Rows.Add(fieldLabel, item.SourceHeader, item.MaskedValue);
            resultsGrid.Rows[rowIndex].Tag = item;
        }

        if (resultsGrid.Rows.Count > 0)
        {
            resultsGrid.CurrentCell = resultsGrid.Rows[0].Cells[0];
            resultsGrid.Rows[0].Selected = true;
        }

        resultsGrid.ResumeLayout();
        baseResultStatus = recommendationsOnly
            ? $"{resultsGrid.Rows.Count} recommended field(s). Use Show all copied fields if needed."
            : query.Length > 0
                ? $"{resultsGrid.Rows.Count} matching copied field(s)."
                : $"{resultsGrid.Rows.Count} copied field(s).";
        UpdateSelectionState();
    }

    private void UpdateSelectionState()
    {
        PickerItem? selected = resultsGrid.SelectedRows.Count == 1
            ? resultsGrid.SelectedRows[0].Tag as PickerItem
            : null;
        pasteButton.Enabled = selected?.IsSafeToPaste == true;
        resultStatus.Text = selected is not null && !selected.IsSafeToPaste
            ? "This value cannot be converted safely for the focused field. Choose another field or enter it manually."
            : baseResultStatus;
    }

    private void ApplyDpiMetrics()
    {
        resultsGrid.ColumnHeadersHeight =
            ResponsiveWindowLayout.ScaleMetric(38, DeviceDpi);
        resultsGrid.RowTemplate.Height =
            ResponsiveWindowLayout.ScaleMetric(34, DeviceDpi);
        foreach (DataGridViewRow row in resultsGrid.Rows)
        {
            row.Height = resultsGrid.RowTemplate.Height;
        }
    }

    private void AcceptSelection()
    {
        if (resultsGrid.SelectedRows.Count != 1 ||
            resultsGrid.SelectedRows[0].Tag is not PickerItem item)
        {
            System.Media.SystemSounds.Beep.Play();
            return;
        }

        if (!item.IsSafeToPaste)
        {
            System.Media.SystemSounds.Beep.Play();
            UpdateSelectionState();
            return;
        }

        SelectedFieldId = item.FieldId;
        DialogResult = DialogResult.OK;
        Close();
    }

    private void CancelOnUiThread()
    {
        if (IsDisposed ||
            Volatile.Read(ref cancellationRequested) == 0)
        {
            return;
        }

        DialogResult = DialogResult.Cancel;
        Close();
    }

    private void OnSearchKeyDown(object? sender, KeyEventArgs eventArgs)
    {
        if (eventArgs.KeyCode == Keys.Down && resultsGrid.Rows.Count > 0)
        {
            resultsGrid.Focus();
            resultsGrid.CurrentCell = resultsGrid.Rows[0].Cells[0];
            eventArgs.SuppressKeyPress = true;
        }
        else if (eventArgs.KeyCode == Keys.Enter)
        {
            AcceptSelection();
            eventArgs.SuppressKeyPress = true;
        }
    }

    private void OnResultsKeyDown(object? sender, KeyEventArgs eventArgs)
    {
        if (eventArgs.KeyCode == Keys.Enter)
        {
            AcceptSelection();
            eventArgs.SuppressKeyPress = true;
        }
        else if (eventArgs.KeyCode == Keys.F && eventArgs.Control)
        {
            searchBox.Focus();
            searchBox.SelectAll();
            eventArgs.SuppressKeyPress = true;
        }
    }

    protected override bool ProcessCmdKey(ref Message message, Keys keyData)
    {
        if (keyData == (Keys.Control | Keys.F))
        {
            searchBox.Focus();
            searchBox.SelectAll();
            return true;
        }

        return base.ProcessCmdKey(ref message, keyData);
    }

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        if (disposing)
        {
            baseUiFont.Dispose();
            targetCaptionFont.Dispose();
            targetValueFont.Dispose();
        }
    }

    private void PositionNearTarget(Rectangle target)
    {
        Rectangle workingArea = target.IsEmpty
            ? Screen.PrimaryScreen?.WorkingArea ?? new Rectangle(0, 0, 1280, 720)
            : Screen.FromRectangle(target).WorkingArea;
        int x = target.IsEmpty ? workingArea.Left + 40 : target.Right + 12;
        int y = target.IsEmpty ? workingArea.Top + 40 : target.Top;
        x = Math.Clamp(x, workingArea.Left, Math.Max(workingArea.Left, workingArea.Right - Width));
        y = Math.Clamp(y, workingArea.Top, Math.Max(workingArea.Top, workingArea.Bottom - Height));
        Location = new Point(x, y);
    }

    private sealed record PickerItem(
        string FieldId,
        string DisplayName,
        string SourceHeader,
        string MaskedValue,
        bool IsRecommended,
        bool IsSafeToPaste,
        string FormatNote,
        int Rank);
}
