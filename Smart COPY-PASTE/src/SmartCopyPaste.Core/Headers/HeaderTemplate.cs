using SmartCopyPaste.Core.Normalization;

namespace SmartCopyPaste.Core.Headers;

public enum HeaderMappingKind
{
    Automatic,
    Manual,
    Custom,
    Ignored,
}

public sealed record HeaderColumnMapping(
    int Ordinal,
    int SourceColumn,
    string OriginalHeader,
    string NormalizedHeader,
    string? FieldId,
    HeaderMappingKind MappingKind);

/// <summary>
/// Versioned mapping of one contiguous spreadsheet header row. Workbook and sheet
/// keys are opaque, user-scoped identifiers; passenger values never belong here.
/// </summary>
public sealed class HeaderTemplate
{
    public const int CurrentSchemaVersion = 1;

    public HeaderTemplate(
        int schemaVersion,
        Guid templateId,
        string workbookKey,
        string sheetKey,
        int headerRow,
        int firstSourceColumn,
        IReadOnlyList<HeaderColumnMapping> columns,
        string orderedHeaderFingerprint,
        int catalogVersion,
        DateTimeOffset createdAt)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(workbookKey);
        ArgumentException.ThrowIfNullOrWhiteSpace(sheetKey);
        ArgumentNullException.ThrowIfNull(columns);
        ArgumentException.ThrowIfNullOrWhiteSpace(orderedHeaderFingerprint);

        if (schemaVersion != CurrentSchemaVersion)
        {
            throw new ArgumentOutOfRangeException(
                nameof(schemaVersion),
                "Unsupported header-template schema version.");
        }

        if (templateId == Guid.Empty)
        {
            throw new ArgumentException("Template identifier cannot be empty.", nameof(templateId));
        }

        ArgumentOutOfRangeException.ThrowIfLessThan(headerRow, 1);
        ArgumentOutOfRangeException.ThrowIfGreaterThan(headerRow, 1_048_576);
        ArgumentOutOfRangeException.ThrowIfLessThan(firstSourceColumn, 1);
        ArgumentOutOfRangeException.ThrowIfGreaterThan(firstSourceColumn, 16_384);
        ArgumentOutOfRangeException.ThrowIfLessThan(catalogVersion, 1);
        if (workbookKey.Length > 256 || sheetKey.Length > 256)
        {
            throw new ArgumentOutOfRangeException(
                nameof(workbookKey),
                "Opaque workbook and sheet keys cannot exceed 256 characters.");
        }

        HeaderColumnMapping[] materialized = columns
            .OrderBy(column => column.Ordinal)
            .ToArray();
        ValidateColumns(materialized, firstSourceColumn);

        string computedFingerprint = HeaderFingerprint.Compute(
            materialized.Select(column => column.OriginalHeader));
        if (!string.Equals(
            computedFingerprint,
            orderedHeaderFingerprint,
            StringComparison.Ordinal))
        {
            throw new ArgumentException(
                "The stored header fingerprint does not match the ordered columns.",
                nameof(orderedHeaderFingerprint));
        }

        SchemaVersion = schemaVersion;
        TemplateId = templateId;
        WorkbookKey = workbookKey;
        SheetKey = sheetKey;
        HeaderRow = headerRow;
        FirstSourceColumn = firstSourceColumn;
        Columns = Array.AsReadOnly(materialized);
        OrderedHeaderFingerprint = orderedHeaderFingerprint;
        CatalogVersion = catalogVersion;
        CreatedAt = createdAt;
    }

    public int SchemaVersion { get; }

    public Guid TemplateId { get; }

    public string WorkbookKey { get; }

    public string SheetKey { get; }

    public int HeaderRow { get; }

    public int FirstSourceColumn { get; }

    public IReadOnlyList<HeaderColumnMapping> Columns { get; }

    public string OrderedHeaderFingerprint { get; }

    public int CatalogVersion { get; }

    public DateTimeOffset CreatedAt { get; }

    public bool MatchesHeaders(IEnumerable<string?> headers)
    {
        ArgumentNullException.ThrowIfNull(headers);
        return string.Equals(
            OrderedHeaderFingerprint,
            HeaderFingerprint.Compute(headers),
            StringComparison.Ordinal);
    }

    private static void ValidateColumns(
        HeaderColumnMapping[] columns,
        int firstSourceColumn)
    {
        if (columns.Length is < 1 or > 128)
        {
            throw new ArgumentOutOfRangeException(
                nameof(columns),
                "A header template must contain between 1 and 128 columns.");
        }

        if (firstSourceColumn + columns.Length - 1 > 16_384)
        {
            throw new ArgumentOutOfRangeException(
                nameof(columns),
                "The header range exceeds the spreadsheet column limit.");
        }

        var activeFieldIds = new HashSet<string>(StringComparer.Ordinal);
        bool hasActiveColumn = false;
        for (int index = 0; index < columns.Length; index++)
        {
            HeaderColumnMapping column = columns[index];
            if (column.Ordinal != index)
            {
                throw new ArgumentException(
                    "Header column ordinals must be contiguous and zero-based.",
                    nameof(columns));
            }

            if (column.SourceColumn != firstSourceColumn + index)
            {
                throw new ArgumentException(
                    "Header source columns must describe one contiguous range.",
                    nameof(columns));
            }

            ArgumentNullException.ThrowIfNull(column.OriginalHeader);
            ArgumentNullException.ThrowIfNull(column.NormalizedHeader);
            if (column.OriginalHeader.Length > 256)
            {
                throw new ArgumentOutOfRangeException(
                    nameof(columns),
                    "A header cell exceeds the 256-character limit.");
            }

            if (!string.Equals(
                column.NormalizedHeader,
                DeterministicTextNormalizer.Normalize(column.OriginalHeader),
                StringComparison.Ordinal))
            {
                throw new ArgumentException(
                    "A stored normalized header does not match its original header.",
                    nameof(columns));
            }

            if (!Enum.IsDefined(column.MappingKind))
            {
                throw new ArgumentException(
                    "A header column contains an unsupported mapping kind.",
                    nameof(columns));
            }

            if (column.MappingKind == HeaderMappingKind.Ignored)
            {
                if (column.FieldId is not null)
                {
                    throw new ArgumentException(
                        "Ignored header columns cannot have a field identifier.",
                        nameof(columns));
                }

                continue;
            }

            hasActiveColumn = true;
            if (string.IsNullOrWhiteSpace(column.FieldId))
            {
                throw new ArgumentException(
                    "Mapped header columns require a field identifier.",
                    nameof(columns));
            }

            if (!IsStableFieldId(column.FieldId))
            {
                throw new ArgumentException(
                    $"Field identifier '{column.FieldId}' is invalid.",
                    nameof(columns));
            }

            if (column.MappingKind == HeaderMappingKind.Custom
                && !column.FieldId.StartsWith("custom.", StringComparison.Ordinal))
            {
                throw new ArgumentException(
                    "Custom header fields must use a custom.* stable identifier.",
                    nameof(columns));
            }

            if (!activeFieldIds.Add(column.FieldId))
            {
                throw new ArgumentException(
                    $"Field '{column.FieldId}' is mapped more than once.",
                    nameof(columns));
            }
        }

        if (!hasActiveColumn)
        {
            throw new ArgumentException(
                "A header template must contain at least one mapped column.",
                nameof(columns));
        }
    }

    private static bool IsStableFieldId(string fieldId)
    {
        return fieldId.Length is >= 3 and <= 96
            && fieldId[0] != '.'
            && fieldId[^1] != '.'
            && fieldId.All(character =>
                character is >= 'a' and <= 'z'
                || character is >= '0' and <= '9'
                || character is '_' or '.');
    }
}
