using System.Text;
using SmartCopyPaste.App.Models;
using SmartCopyPaste.Core.Headers;

namespace SmartCopyPaste.App.Services;

internal static class HeaderTemplateAdapter
{
    internal static HeaderTemplate ToCore(HeaderTemplateRecord stored)
    {
        ArgumentNullException.ThrowIfNull(stored);
        if (!Guid.TryParseExact(stored.TemplateId, "N", out Guid templateId) &&
            !Guid.TryParse(stored.TemplateId, out templateId))
        {
            throw new InvalidDataException("A stored header profile has an invalid identifier.");
        }

        HeaderColumnMapping[] columns = stored.Columns
            .OrderBy(static column => column.Offset)
            .Select(column => new HeaderColumnMapping(
                column.Offset,
                stored.FirstColumn + column.Offset,
                column.OriginalHeader,
                SmartCopyPaste.Core.Normalization.DeterministicTextNormalizer.Normalize(column.OriginalHeader),
                column.Ignored ? null : column.CanonicalFieldId,
                column.Ignored
                    ? HeaderMappingKind.Ignored
                    : column.CanonicalFieldId.StartsWith("custom.", StringComparison.Ordinal)
                        ? HeaderMappingKind.Custom
                        : HeaderMappingKind.Manual))
            .ToArray();

        return new HeaderTemplate(
            HeaderTemplate.CurrentSchemaVersion,
            templateId,
            stored.WorkbookIdentity,
            stored.WorksheetIdentity,
            stored.HeaderRow,
            stored.FirstColumn,
            columns,
            stored.HeaderFingerprint,
            SmartCopyPaste.Core.Catalog.CanonicalFieldCatalog.CurrentVersion,
            DateTimeOffset.UtcNow);
    }

    internal static HeaderTemplateRecord FromCore(
        HeaderTemplate template,
        string displayName,
        bool sessionOnly)
    {
        ArgumentNullException.ThrowIfNull(template);
        ArgumentException.ThrowIfNullOrWhiteSpace(displayName);
        return new HeaderTemplateRecord
        {
            SchemaVersion = HeaderTemplate.CurrentSchemaVersion,
            TemplateId = template.TemplateId.ToString("N"),
            DisplayName = displayName.Trim(),
            WorkbookIdentity = template.WorkbookKey,
            WorksheetIdentity = template.SheetKey,
            HeaderRow = template.HeaderRow,
            FirstColumn = template.FirstSourceColumn,
            ColumnCount = template.Columns.Count,
            HeaderFingerprint = template.OrderedHeaderFingerprint,
            SessionOnly = sessionOnly,
            Columns = template.Columns.Select(static column => new HeaderColumnRecord
            {
                Offset = column.Ordinal,
                OriginalHeader = column.OriginalHeader,
                CanonicalFieldId = column.FieldId ?? string.Empty,
                Ignored = column.MappingKind == HeaderMappingKind.Ignored,
            }).ToList(),
        };
    }

    internal static string SerializeRows(IReadOnlyList<IReadOnlyList<string>> rows)
    {
        ArgumentNullException.ThrowIfNull(rows);
        var result = new StringBuilder();
        for (int rowIndex = 0; rowIndex < rows.Count; rowIndex++)
        {
            IReadOnlyList<string> row = rows[rowIndex];
            for (int columnIndex = 0; columnIndex < row.Count; columnIndex++)
            {
                if (columnIndex > 0)
                {
                    result.Append('\t');
                }

                AppendEscapedCell(result, row[columnIndex]);
            }

            if (rowIndex < rows.Count - 1)
            {
                result.Append("\r\n");
            }
        }

        return result.ToString();
    }

    internal static IReadOnlyDictionary<string, string> GetSourceHeaders(HeaderTemplateRecord template)
    {
        ArgumentNullException.ThrowIfNull(template);
        return template.Columns
            .Where(static column => !column.Ignored && !string.IsNullOrWhiteSpace(column.CanonicalFieldId))
            .GroupBy(static column => column.CanonicalFieldId, StringComparer.Ordinal)
            .ToDictionary(
                static group => group.Key,
                static group => group.First().OriginalHeader,
                StringComparer.Ordinal);
    }

    private static void AppendEscapedCell(StringBuilder output, string value)
    {
        value ??= string.Empty;
        if (value.IndexOfAny(['\t', '\r', '\n', '"']) < 0)
        {
            output.Append(value);
            return;
        }

        output.Append('"');
        output.Append(value.Replace("\"", "\"\"", StringComparison.Ordinal));
        output.Append('"');
    }
}
