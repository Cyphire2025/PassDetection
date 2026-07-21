using SmartCopyPaste.Core.Catalog;
using SmartCopyPaste.Core.Headers;
using SmartCopyPaste.App.Services;

namespace SmartCopyPaste.App.Forms;

internal sealed class HeaderMappingDialog : Form
{
    private const string IgnoreChoice = "__ignore__";
    private const string CustomChoice = "__custom__";
    private readonly IReadOnlyList<string> headers;
    private readonly CanonicalFieldCatalog catalog;
    private readonly TextBox templateName = new();
    private readonly DataGridView mappingsGrid = new();
    private readonly Label mappingStatus = new();
    private readonly Font baseUiFont =
        new("Segoe UI", 10.5F, FontStyle.Regular, GraphicsUnit.Point);
    private bool mappingDataError;

    internal HeaderMappingDialog(
        IReadOnlyList<string> headers,
        string suggestedTemplateName,
        CanonicalFieldCatalog? catalog = null)
    {
        ArgumentNullException.ThrowIfNull(headers);
        this.headers = headers;
        this.catalog = catalog ?? CanonicalFieldCatalog.Default;

        Font = baseUiFont;
        Text = "Save header profile";
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.Sizable;
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96F, 96F);
        Size = new Size(920, 680);
        MinimumSize = new Size(700, 500);
        AccessibleName = "Save Excel header profile";

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
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        Controls.Add(root);

        root.Controls.Add(new Label
        {
            Text = "Review the selected header row. Unknown headers must be mapped, kept as custom fields, or ignored.",
            AutoSize = true,
            Dock = DockStyle.Fill,
            Margin = new Padding(0, 0, 0, 10),
            AccessibleName = "Header mapping instructions",
        });

        var namePanel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            ColumnCount = 2,
            Margin = new Padding(0, 0, 0, 10),
        };
        namePanel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        namePanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        namePanel.Controls.Add(new Label
        {
            Text = "Profile name:",
            AutoSize = true,
            Margin = new Padding(0, 8, 10, 0),
        });
        templateName.MaxLength = 120;
        templateName.Text = suggestedTemplateName.Length <= templateName.MaxLength
            ? suggestedTemplateName
            : suggestedTemplateName[..templateName.MaxLength];
        templateName.Dock = DockStyle.Fill;
        templateName.MinimumSize = new Size(0, 34);
        templateName.AccessibleName = "Header profile name";
        namePanel.Controls.Add(templateName);
        root.Controls.Add(namePanel);

        mappingStatus.AutoSize = true;
        mappingStatus.Dock = DockStyle.Fill;
        mappingStatus.ForeColor = SystemColors.GrayText;
        mappingStatus.Margin = new Padding(0, 0, 0, 8);
        mappingStatus.AccessibleName = "Header mapping status";
        root.Controls.Add(mappingStatus);

        ConfigureMappingsGrid();
        root.Controls.Add(mappingsGrid);

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            FlowDirection = FlowDirection.RightToLeft,
            Margin = new Padding(0, 10, 0, 0),
        };
        Button cancel = new() { Text = "Cancel", AutoSize = true, DialogResult = DialogResult.Cancel };
        cancel.MinimumSize = new Size(100, 40);
        Button save = new()
        {
            Text = "Save Header Profile",
            AutoSize = true,
            MinimumSize = new Size(180, 40),
        };
        save.Click += (_, _) => SaveMapping();
        buttons.Controls.Add(cancel);
        buttons.Controls.Add(save);
        root.Controls.Add(buttons);
        AcceptButton = save;
        CancelButton = cancel;

        Shown += (_, _) =>
        {
            ApplyDpiMetrics();
            ResponsiveWindowLayout.ClampToWorkingArea(
                this,
                new Size(700, 500));
        };
        DpiChanged += (_, _) =>
        {
            ApplyDpiMetrics();
            ResponsiveWindowLayout.ClampToWorkingArea(
                this,
                new Size(700, 500));
        };
    }

    internal string TemplateDisplayName => templateName.Text.Trim();

    internal IReadOnlyDictionary<int, HeaderMappingOverride> MappingOverrides { get; private set; } =
        new Dictionary<int, HeaderMappingOverride>();

    internal bool HadMappingDataError => mappingDataError;

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        if (disposing)
        {
            baseUiFont.Dispose();
        }
    }

    private void ConfigureMappingsGrid()
    {
        mappingsGrid.Dock = DockStyle.Fill;
        mappingsGrid.AllowUserToAddRows = false;
        mappingsGrid.AllowUserToDeleteRows = false;
        mappingsGrid.AllowUserToResizeRows = false;
        mappingsGrid.AllowUserToOrderColumns = false;
        mappingsGrid.RowHeadersVisible = false;
        mappingsGrid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill;
        mappingsGrid.SelectionMode = DataGridViewSelectionMode.CellSelect;
        mappingsGrid.BackgroundColor = SystemColors.Window;
        mappingsGrid.BorderStyle = BorderStyle.FixedSingle;
        mappingsGrid.ColumnHeadersHeight = 38;
        mappingsGrid.ColumnHeadersHeightSizeMode =
            DataGridViewColumnHeadersHeightSizeMode.DisableResizing;
        mappingsGrid.RowTemplate.Height = 36;
        mappingsGrid.AccessibleName = "Excel header mappings";
        mappingsGrid.DataError += (_, eventArgs) =>
        {
            mappingDataError = true;
            eventArgs.ThrowException = true;
        };

        var sourceColumn = new DataGridViewTextBoxColumn
        {
            Name = "source",
            HeaderText = "Excel header",
            ReadOnly = true,
            FillWeight = 34,
            MinimumWidth = 190,
        };
        var mappingColumn = new DataGridViewComboBoxColumn
        {
            Name = "mapping",
            HeaderText = "Use as",
            DisplayMember = nameof(HeaderChoice.DisplayName),
            ValueMember = nameof(HeaderChoice.Id),
            DataSource = CreateChoices(),
            FlatStyle = FlatStyle.Flat,
            FillWeight = 42,
            MinimumWidth = 240,
        };
        var statusColumn = new DataGridViewTextBoxColumn
        {
            Name = "status",
            HeaderText = "Status",
            ReadOnly = true,
            FillWeight = 24,
            MinimumWidth = 150,
        };
        mappingsGrid.Columns.AddRange(sourceColumn, mappingColumn, statusColumn);
        mappingsGrid.CurrentCellDirtyStateChanged += (_, _) =>
        {
            if (mappingsGrid.IsCurrentCellDirty)
            {
                _ = mappingsGrid.CommitEdit(DataGridViewDataErrorContexts.Commit);
            }
        };
        mappingsGrid.CellValueChanged += (_, eventArgs) =>
        {
            if (eventArgs.RowIndex >= 0 &&
                mappingsGrid.Columns[eventArgs.ColumnIndex].Name == "mapping")
            {
                UpdateRowStatus(eventArgs.RowIndex);
            }
        };

        int reviewCount = 0;
        for (int index = 0; index < headers.Count; index++)
        {
            string header = headers[index];
            AliasMatch match = catalog.ResolveHeader(header);
            bool automatic = match.Status == AliasMatchStatus.Unique;
            bool customByDefault = !automatic && !string.IsNullOrWhiteSpace(header);
            string initial = automatic
                ? match.CanonicalFieldId!
                : customByDefault
                    ? CustomChoice
                    : string.Empty;
            string status = automatic
                ? "Matched automatically"
                : customByDefault
                    ? "Custom field — review"
                    : "Choose handling";
            _ = mappingsGrid.Rows.Add(header, initial, status);
            mappingsGrid.Rows[index].Tag = index;
            if (customByDefault)
            {
                mappingsGrid.Rows[index].DefaultCellStyle.BackColor = SystemColors.Info;
                reviewCount++;
            }
        }

        mappingStatus.Text = reviewCount == 0
            ? $"{headers.Count} column(s) recognized."
            : $"{headers.Count} column(s) • {reviewCount} unknown nonblank header(s) kept safely as custom fields for review.";
    }

    private void UpdateRowStatus(int rowIndex)
    {
        DataGridViewRow row = mappingsGrid.Rows[rowIndex];
        string selected = Convert.ToString(
            row.Cells["mapping"].Value,
            System.Globalization.CultureInfo.InvariantCulture) ?? string.Empty;
        string status = selected switch
        {
            "" => "Choose handling",
            IgnoreChoice => "Ignored",
            CustomChoice => "Custom field — review",
            _ => "Mapped",
        };
        row.Cells["status"].Value = status;
        row.DefaultCellStyle.BackColor =
            selected == CustomChoice ? SystemColors.Info : SystemColors.Window;
    }

    private void ApplyDpiMetrics()
    {
        mappingsGrid.ColumnHeadersHeight =
            ResponsiveWindowLayout.ScaleMetric(38, DeviceDpi);
        mappingsGrid.RowTemplate.Height =
            ResponsiveWindowLayout.ScaleMetric(36, DeviceDpi);
        foreach (DataGridViewRow row in mappingsGrid.Rows)
        {
            row.Height = mappingsGrid.RowTemplate.Height;
        }
    }

    private System.Collections.ObjectModel.ReadOnlyCollection<HeaderChoice> CreateChoices()
    {
        var choices = new List<HeaderChoice>
        {
            new(string.Empty, "Select a mapping…"),
            new(IgnoreChoice, "Ignore this column"),
            new(CustomChoice, "Keep as a custom field"),
        };
        choices.AddRange(catalog.Definitions
            .OrderBy(static definition => definition.FieldGroup, StringComparer.CurrentCulture)
            .ThenBy(static definition => definition.DisplayName, StringComparer.CurrentCulture)
            .Select(static definition => new HeaderChoice(
                definition.Id,
                $"{definition.FieldGroup} — {definition.DisplayName}")));
        return choices.AsReadOnly();
    }

    private void SaveMapping()
    {
        if (string.IsNullOrWhiteSpace(TemplateDisplayName))
        {
            MessageBox.Show(
                this,
                "Enter a name for this header profile.",
                "Header profile",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning);
            templateName.Focus();
            return;
        }

        var overrides = new Dictionary<int, HeaderMappingOverride>();
        var selectedFields = new HashSet<string>(StringComparer.Ordinal);
        for (int index = 0; index < mappingsGrid.Rows.Count; index++)
        {
            string header = headers[index];
            string? selected = Convert.ToString(
                mappingsGrid.Rows[index].Cells["mapping"].Value,
                System.Globalization.CultureInfo.InvariantCulture);
            if (string.IsNullOrWhiteSpace(selected))
            {
                MessageBox.Show(
                    this,
                    $"Choose how to handle the header “{header}”.",
                    "Header mapping required",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning);
                mappingsGrid.CurrentCell = mappingsGrid.Rows[index].Cells["mapping"];
                return;
            }

            AliasMatch automatic = catalog.ResolveHeader(header);
            if (selected == IgnoreChoice)
            {
                overrides[index] = new HeaderMappingOverride(HeaderMappingKind.Ignored, null);
            }
            else if (selected == CustomChoice)
            {
                if (string.IsNullOrWhiteSpace(header))
                {
                    MessageBox.Show(
                        this,
                        "A blank header cannot become a custom field. Map it to a known field or ignore the column.",
                        "Header mapping required",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Warning);
                    mappingsGrid.CurrentCell = mappingsGrid.Rows[index].Cells["mapping"];
                    return;
                }

                string customId = HeaderTemplateFactory.CreateCustomFieldId(header);
                if (!selectedFields.Add(customId))
                {
                    ShowDuplicateMapping(header);
                    return;
                }

                overrides[index] = new HeaderMappingOverride(HeaderMappingKind.Custom, customId);
            }
            else
            {
                if (!selectedFields.Add(selected))
                {
                    ShowDuplicateMapping(header);
                    return;
                }

                if (automatic.Status != AliasMatchStatus.Unique ||
                    !string.Equals(automatic.CanonicalFieldId, selected, StringComparison.Ordinal))
                {
                    overrides[index] = new HeaderMappingOverride(HeaderMappingKind.Manual, selected);
                }
            }
        }

        MappingOverrides = overrides;
        DialogResult = DialogResult.OK;
        Close();
    }

    private void ShowDuplicateMapping(string header) =>
        MessageBox.Show(
            this,
            $"The mapping for “{header}” duplicates another field. Each passenger field can be mapped only once.",
            "Duplicate mapping",
            MessageBoxButtons.OK,
            MessageBoxIcon.Warning);

    private sealed record HeaderChoice(string Id, string DisplayName);
}
