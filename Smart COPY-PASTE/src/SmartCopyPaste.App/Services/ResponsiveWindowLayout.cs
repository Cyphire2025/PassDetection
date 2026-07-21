namespace SmartCopyPaste.App.Services;

internal static class ResponsiveWindowLayout
{
    internal static int ScaleMetric(int logicalPixels, int dpi)
    {
        ArgumentOutOfRangeException.ThrowIfLessThan(logicalPixels, 1);
        ArgumentOutOfRangeException.ThrowIfLessThan(dpi, 48);
        ArgumentOutOfRangeException.ThrowIfGreaterThan(dpi, 768);
        return Math.Max(
            1,
            (int)Math.Round(
                logicalPixels * (dpi / 96D),
                MidpointRounding.AwayFromZero));
    }

    internal static void ClampToWorkingArea(
        Form form,
        Size logicalMinimumSize,
        Rectangle targetBounds = default)
    {
        ArgumentNullException.ThrowIfNull(form);
        Screen? screen = targetBounds.IsEmpty
            ? Screen.FromControl(form)
            : Screen.FromRectangle(targetBounds);
        Rectangle workingArea =
            screen?.WorkingArea ??
            Screen.PrimaryScreen?.WorkingArea ??
            new Rectangle(0, 0, 1280, 720);
        int margin = ScaleMetric(12, form.DeviceDpi);
        int maximumWidth = Math.Max(320, workingArea.Width - (margin * 2));
        int maximumHeight = Math.Max(280, workingArea.Height - (margin * 2));
        int minimumWidth = Math.Min(
            ScaleMetric(logicalMinimumSize.Width, form.DeviceDpi),
            maximumWidth);
        int minimumHeight = Math.Min(
            ScaleMetric(logicalMinimumSize.Height, form.DeviceDpi),
            maximumHeight);
        form.MinimumSize = new Size(minimumWidth, minimumHeight);
        form.Size = new Size(
            Math.Clamp(form.Width, minimumWidth, maximumWidth),
            Math.Clamp(form.Height, minimumHeight, maximumHeight));
        form.Location = new Point(
            Math.Clamp(
                form.Left,
                workingArea.Left + margin,
                Math.Max(
                    workingArea.Left + margin,
                    workingArea.Right - margin - form.Width)),
            Math.Clamp(
                form.Top,
                workingArea.Top + margin,
                Math.Max(
                    workingArea.Top + margin,
                    workingArea.Bottom - margin - form.Height)));
    }
}
