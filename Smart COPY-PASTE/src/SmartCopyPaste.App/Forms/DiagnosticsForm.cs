namespace SmartCopyPaste.App.Forms;

using SmartCopyPaste.App.Services;

internal sealed class DiagnosticsForm : Form
{
    private readonly Font baseUiFont =
        new("Segoe UI", 10.5F, FontStyle.Regular, GraphicsUnit.Point);
    private readonly Font headingFont =
        new("Segoe UI", 16F, FontStyle.Bold, GraphicsUnit.Point);
    private readonly Font reportFont =
        new("Consolas", 10.5F, FontStyle.Regular, GraphicsUnit.Point);

    internal DiagnosticsForm(string sanitizedReport)
    {
        ArgumentNullException.ThrowIfNull(sanitizedReport);

        Font = baseUiFont;
        Text = "Smart COPY/PASTE Diagnostics";
        AccessibleName = "Smart COPY/PASTE sanitized diagnostics";
        StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.Sizable;
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96F, 96F);
        Size = new Size(820, 600);
        MinimumSize = new Size(700, 500);
        ShowInTaskbar = false;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Padding = new Padding(20),
            ColumnCount = 1,
            RowCount = 4,
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        Controls.Add(root);

        root.Controls.Add(new Label
        {
            Text = "Sanitized diagnostics",
            AutoSize = true,
            Font = headingFont,
            Margin = new Padding(0, 0, 0, 4),
            AccessibleRole = AccessibleRole.StaticText,
        });
        root.Controls.Add(new Label
        {
            Text = "This report contains application state and reason codes, not passenger values or website labels.",
            AutoSize = true,
            Dock = DockStyle.Fill,
            ForeColor = SystemColors.GrayText,
            Margin = new Padding(0, 0, 0, 12),
            AccessibleRole = AccessibleRole.StaticText,
        });

        var report = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Both,
            WordWrap = false,
            Font = reportFont,
            Text = sanitizedReport,
            AccessibleName = "Sanitized diagnostic report",
        };
        root.Controls.Add(report);

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            FlowDirection = FlowDirection.RightToLeft,
            WrapContents = false,
            Margin = new Padding(0, 12, 0, 0),
        };
        Button close = new()
        {
            Text = "Close",
            AutoSize = true,
            MinimumSize = new Size(100, 40),
            DialogResult = DialogResult.OK,
        };
        Button copy = new()
        {
            Text = "Copy sanitized report",
            AutoSize = true,
            MinimumSize = new Size(190, 40),
        };
        copy.Click += (_, _) => CopyReport(sanitizedReport);
        buttons.Controls.Add(close);
        buttons.Controls.Add(copy);
        root.Controls.Add(buttons);
        AcceptButton = close;
        CancelButton = close;

        Shown += (_, _) => ResponsiveWindowLayout.ClampToWorkingArea(
            this,
            new Size(700, 500));
        DpiChanged += (_, _) => ResponsiveWindowLayout.ClampToWorkingArea(
            this,
            new Size(700, 500));
    }

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        if (disposing)
        {
            baseUiFont.Dispose();
            headingFont.Dispose();
            reportFont.Dispose();
        }
    }

    private void CopyReport(string sanitizedReport)
    {
        try
        {
            Clipboard.SetText(sanitizedReport, TextDataFormat.UnicodeText);
        }
        catch (System.Runtime.InteropServices.ExternalException)
        {
            MessageBox.Show(
                this,
                "Windows could not access the clipboard. Close other clipboard tools and try again.",
                "Clipboard unavailable",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning);
        }
    }
}
