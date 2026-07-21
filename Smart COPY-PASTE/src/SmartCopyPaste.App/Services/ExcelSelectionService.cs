using System.Diagnostics;
using System.Runtime.InteropServices;
using SmartCopyPaste.App.Interop;

namespace SmartCopyPaste.App.Services;

internal sealed record ExcelSelectionContext(
    bool IsExcelSelection,
    string WorkbookIdentity,
    string WorksheetIdentity,
    string SuggestedTemplateName,
    bool SessionOnly,
    int FirstRow,
    int FirstColumn,
    int RowCount,
    int ColumnCount,
    IReadOnlyList<IReadOnlyList<string>> DisplayRows,
    nint ForegroundWindow,
    string? ErrorCode)
{
    internal bool AllowsClipboardFallback =>
        !IsExcelSelection &&
        ErrorCode is null or
            "EXCEL_TIMEOUT" or
            "EXCEL_SELECTION_UNAVAILABLE" or
            "EXCEL_FOREGROUND_INSTANCE_MISMATCH";

    internal static ExcelSelectionContext NotExcel(nint foregroundWindow) =>
        new(
            false,
            string.Empty,
            string.Empty,
            "Clipboard profile",
            true,
            1,
            1,
            0,
            0,
            Array.Empty<IReadOnlyList<string>>(),
            foregroundWindow,
            null);

    internal static ExcelSelectionContext Failure(nint foregroundWindow, string errorCode) =>
        NotExcel(foregroundWindow) with { ErrorCode = errorCode };
}

internal sealed class ExcelSelectionService
{
    internal static async Task<ExcelSelectionContext> InspectAsync(
        byte[] userSecret,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(userSecret);
        nint foregroundWindow = NativeMethods.GetForegroundWindow();
        if (!TryGetForegroundProcessName(foregroundWindow, out string processName) ||
            !string.Equals(processName, "EXCEL", StringComparison.OrdinalIgnoreCase))
        {
            return ExcelSelectionContext.NotExcel(foregroundWindow);
        }

        try
        {
            Task<ExcelSelectionContext> inspection = StaTaskRunner.RunAsync(
                () => InspectOnSta(userSecret, foregroundWindow),
                cancellationToken);
            Task completed = await Task.WhenAny(
                inspection,
                Task.Delay(TimeSpan.FromSeconds(3), cancellationToken)).ConfigureAwait(true);
            if (completed != inspection)
            {
                return ExcelSelectionContext.Failure(foregroundWindow, "EXCEL_TIMEOUT");
            }

            return await inspection.ConfigureAwait(true);
        }
        catch (Exception exception) when (
            exception is COMException or
            InvalidCastException or
            Microsoft.CSharp.RuntimeBinder.RuntimeBinderException)
        {
            return ExcelSelectionContext.Failure(foregroundWindow, "EXCEL_SELECTION_UNAVAILABLE");
        }
    }

    internal static async Task<bool> VerifyHeaderTemplateAsync(
        byte[] userSecret,
        ExcelSelectionContext selectionContext,
        SmartCopyPaste.App.Models.HeaderTemplateRecord template,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(userSecret);
        ArgumentNullException.ThrowIfNull(selectionContext);
        ArgumentNullException.ThrowIfNull(template);
        if (!selectionContext.IsExcelSelection)
        {
            return false;
        }

        try
        {
            Task<bool> verification = StaTaskRunner.RunAsync(
                () => VerifyHeaderOnSta(
                    userSecret,
                    selectionContext.ForegroundWindow,
                    template),
                cancellationToken);
            Task completed = await Task.WhenAny(
                verification,
                Task.Delay(TimeSpan.FromSeconds(3), cancellationToken)).ConfigureAwait(true);
            return completed == verification && await verification.ConfigureAwait(true);
        }
        catch (Exception exception) when (
            exception is COMException or
            InvalidCastException or
            Microsoft.CSharp.RuntimeBinder.RuntimeBinderException)
        {
            return false;
        }
    }

    private static ExcelSelectionContext InspectOnSta(byte[] userSecret, nint foregroundWindow)
    {
        object? application = null;
        object? selection = null;
        object? areas = null;
        object? rows = null;
        object? columns = null;
        object? cells = null;
        object? worksheet = null;
        object? workbook = null;
        try
        {
            application = NativeMethods.GetActiveComObject("Excel.Application");
            dynamic excel = application;
            nint excelWindow = new(Convert.ToInt64(
                excel.Hwnd,
                System.Globalization.CultureInfo.InvariantCulture));
            if (excelWindow != foregroundWindow)
            {
                return ExcelSelectionContext.Failure(
                    foregroundWindow,
                    "EXCEL_FOREGROUND_INSTANCE_MISMATCH");
            }

            selection = excel.Selection;
            if (selection is null)
            {
                return ExcelSelectionContext.Failure(foregroundWindow, "EXCEL_NO_SELECTION");
            }

            dynamic range = selection;
            areas = range.Areas;
            dynamic rangeAreas = areas;
            int areaCount = Convert.ToInt32(
                rangeAreas.Count,
                System.Globalization.CultureInfo.InvariantCulture);
            if (areaCount != 1)
            {
                return ExcelSelectionContext.Failure(foregroundWindow, "EXCEL_MULTI_AREA_SELECTION");
            }

            rows = range.Rows;
            columns = range.Columns;
            dynamic rangeRows = rows;
            dynamic rangeColumns = columns;
            int rowCount = Convert.ToInt32(
                rangeRows.Count,
                System.Globalization.CultureInfo.InvariantCulture);
            int columnCount = Convert.ToInt32(
                rangeColumns.Count,
                System.Globalization.CultureInfo.InvariantCulture);
            int firstRow = Convert.ToInt32(range.Row, System.Globalization.CultureInfo.InvariantCulture);
            int firstColumn = Convert.ToInt32(range.Column, System.Globalization.CultureInfo.InvariantCulture);
            if (rowCount is < 1 or > 100 || columnCount is < 1 or > 128)
            {
                return ExcelSelectionContext.Failure(foregroundWindow, "EXCEL_SELECTION_SIZE_INVALID");
            }

            object? mergedValue = range.MergeCells;
            if (mergedValue is null ||
                !bool.TryParse(
                    Convert.ToString(
                        mergedValue,
                        System.Globalization.CultureInfo.InvariantCulture),
                    out bool hasMergedCells) ||
                hasMergedCells)
            {
                return ExcelSelectionContext.Failure(foregroundWindow, "EXCEL_MERGED_SELECTION");
            }

            cells = range.Cells;
            dynamic rangeCells = cells;
            var displayRows = new List<IReadOnlyList<string>>(rowCount);
            for (int rowIndex = 1; rowIndex <= rowCount; rowIndex++)
            {
                var displayRow = new string[columnCount];
                for (int columnIndex = 1; columnIndex <= columnCount; columnIndex++)
                {
                    object? cell = null;
                    try
                    {
                        cell = rangeCells.Item[rowIndex, columnIndex];
                        dynamic excelCell = cell;
                        string text = Convert.ToString(
                            excelCell.Text,
                            System.Globalization.CultureInfo.CurrentCulture) ?? string.Empty;
                        if (text.Length >= 3 && text.All(static character => character == '#'))
                        {
                            return ExcelSelectionContext.Failure(
                                foregroundWindow,
                                "EXCEL_DISPLAY_VALUE_OBSCURED");
                        }

                        displayRow[columnIndex - 1] = text;
                    }
                    finally
                    {
                        ReleaseComReference(cell);
                    }
                }

                displayRows.Add(Array.AsReadOnly(displayRow));
            }

            worksheet = range.Worksheet;
            dynamic sheet = worksheet;
            workbook = sheet.Parent;
            dynamic book = workbook;

            string fullName = Convert.ToString(book.FullName, System.Globalization.CultureInfo.InvariantCulture) ?? string.Empty;
            string path = Convert.ToString(book.Path, System.Globalization.CultureInfo.InvariantCulture) ?? string.Empty;
            string bookName = FirstNonBlank(
                Convert.ToString(book.Name, System.Globalization.CultureInfo.InvariantCulture),
                null,
                "Workbook");
            string sheetCodeName = ResolveWorksheetIdentityName(
                Convert.ToString(sheet.CodeName, System.Globalization.CultureInfo.InvariantCulture),
                Convert.ToString(sheet.Name, System.Globalization.CultureInfo.InvariantCulture));
            bool sessionOnly = string.IsNullOrWhiteSpace(path);

            string workbookIdentity = sessionOnly
                ? $"SESSION-{Environment.ProcessId}-{bookName.GetHashCode(StringComparison.Ordinal):X8}"
                : WorkbookIdentityService.ComputeWorkbookIdentity(userSecret, fullName);
            string worksheetIdentity = WorkbookIdentityService.ComputeWorksheetIdentity(
                userSecret,
                workbookIdentity,
                sheetCodeName);
            string suggestedName = sessionOnly
                ? $"{bookName} / {sheetCodeName} (this session)"
                : $"{bookName} / {sheetCodeName}";

            return new ExcelSelectionContext(
                true,
                workbookIdentity,
                worksheetIdentity,
                suggestedName,
                sessionOnly,
                firstRow,
                firstColumn,
                rowCount,
                columnCount,
                displayRows.AsReadOnly(),
                foregroundWindow,
                null);
        }
        finally
        {
            ReleaseComReference(workbook);
            ReleaseComReference(worksheet);
            ReleaseComReference(columns);
            ReleaseComReference(rows);
            ReleaseComReference(areas);
            ReleaseComReference(cells);
            ReleaseComReference(selection);
            ReleaseComReference(application);
        }
    }

    private static bool VerifyHeaderOnSta(
        byte[] userSecret,
        nint foregroundWindow,
        SmartCopyPaste.App.Models.HeaderTemplateRecord template)
    {
        object? application = null;
        object? worksheet = null;
        object? workbook = null;
        object? cells = null;
        try
        {
            application = NativeMethods.GetActiveComObject("Excel.Application");
            dynamic excel = application;
            nint excelWindow = new(Convert.ToInt64(
                excel.Hwnd,
                System.Globalization.CultureInfo.InvariantCulture));
            if (excelWindow != foregroundWindow)
            {
                return false;
            }

            worksheet = excel.ActiveSheet;
            dynamic sheet = worksheet;
            workbook = sheet.Parent;
            dynamic book = workbook;
            string fullName = Convert.ToString(
                book.FullName,
                System.Globalization.CultureInfo.InvariantCulture) ?? string.Empty;
            string path = Convert.ToString(
                book.Path,
                System.Globalization.CultureInfo.InvariantCulture) ?? string.Empty;
            string bookName = FirstNonBlank(
                Convert.ToString(
                    book.Name,
                    System.Globalization.CultureInfo.InvariantCulture),
                null,
                "Workbook");
            string sheetCodeName = ResolveWorksheetIdentityName(
                Convert.ToString(
                    sheet.CodeName,
                    System.Globalization.CultureInfo.InvariantCulture),
                Convert.ToString(
                    sheet.Name,
                    System.Globalization.CultureInfo.InvariantCulture));
            string workbookIdentity = string.IsNullOrWhiteSpace(path)
                ? $"SESSION-{Environment.ProcessId}-{bookName.GetHashCode(StringComparison.Ordinal):X8}"
                : WorkbookIdentityService.ComputeWorkbookIdentity(userSecret, fullName);
            string worksheetIdentity = WorkbookIdentityService.ComputeWorksheetIdentity(
                userSecret,
                workbookIdentity,
                sheetCodeName);
            if (!string.Equals(
                    workbookIdentity,
                    template.WorkbookIdentity,
                    StringComparison.Ordinal) ||
                !string.Equals(
                    worksheetIdentity,
                    template.WorksheetIdentity,
                    StringComparison.Ordinal))
            {
                return false;
            }

            cells = sheet.Cells;
            dynamic sheetCells = cells;
            var headers = new string[template.ColumnCount];
            for (int offset = 0; offset < template.ColumnCount; offset++)
            {
                object? cell = null;
                try
                {
                    cell = sheetCells.Item[
                        template.HeaderRow,
                        template.FirstColumn + offset];
                    dynamic excelCell = cell;
                    string value = Convert.ToString(
                        excelCell.Text,
                        System.Globalization.CultureInfo.CurrentCulture) ?? string.Empty;
                    if (value.Length >= 3 && value.All(static character => character == '#'))
                    {
                        return false;
                    }

                    headers[offset] = value;
                }
                finally
                {
                    ReleaseComReference(cell);
                }
            }

            string fingerprint = SmartCopyPaste.Core.Headers.HeaderFingerprint.Compute(headers);
            return string.Equals(
                fingerprint,
                template.HeaderFingerprint,
                StringComparison.Ordinal);
        }
        finally
        {
            ReleaseComReference(cells);
            ReleaseComReference(workbook);
            ReleaseComReference(worksheet);
            ReleaseComReference(application);
        }
    }

    private static bool TryGetForegroundProcessName(nint window, out string processName)
    {
        processName = string.Empty;
        _ = NativeMethods.GetWindowThreadProcessId(window, out uint processId);
        if (processId == 0)
        {
            return false;
        }

        try
        {
            using Process process = Process.GetProcessById(checked((int)processId));
            processName = process.ProcessName;
            return true;
        }
        catch (ArgumentException)
        {
            return false;
        }
    }

    internal static string ResolveWorksheetIdentityName(
        string? worksheetCodeName,
        string? worksheetName) =>
        FirstNonBlank(worksheetCodeName, worksheetName, "Sheet");

    private static string FirstNonBlank(
        string? preferred,
        string? alternate,
        string fallback)
    {
        if (!string.IsNullOrWhiteSpace(preferred))
        {
            return preferred;
        }

        return !string.IsNullOrWhiteSpace(alternate)
            ? alternate
            : fallback;
    }

    private static void ReleaseComReference(object? value)
    {
        if (value is not null && Marshal.IsComObject(value))
        {
            _ = Marshal.ReleaseComObject(value);
        }
    }
}
