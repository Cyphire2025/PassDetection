using System.Security.Cryptography;
using System.Text;
using System.Globalization;
using SmartCopyPaste.Core.Catalog;
using SmartCopyPaste.Core.Normalization;

namespace SmartCopyPaste.Core.Headers;

public sealed record HeaderMappingOverride(
    HeaderMappingKind MappingKind,
    string? FieldId);

public sealed record HeaderTemplateIssue(
    string Code,
    string Message,
    int? ColumnOrdinal = null);

public sealed record HeaderTemplateCreateResult(
    HeaderTemplate? Template,
    IReadOnlyList<HeaderTemplateIssue> Issues)
{
    public bool Success => Template is not null && Issues.Count == 0;
}

public static class HeaderTemplateFactory
{
    public static HeaderTemplateCreateResult Create(
        string workbookKey,
        string sheetKey,
        int headerRow,
        int firstSourceColumn,
        IReadOnlyList<string?> headers,
        CanonicalFieldCatalog catalog,
        IReadOnlyDictionary<int, HeaderMappingOverride>? overrides = null,
        DateTimeOffset? createdAt = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(workbookKey);
        ArgumentException.ThrowIfNullOrWhiteSpace(sheetKey);
        ArgumentNullException.ThrowIfNull(headers);
        ArgumentNullException.ThrowIfNull(catalog);

        var issues = new List<HeaderTemplateIssue>();
        if (workbookKey.Length > 256 || sheetKey.Length > 256)
        {
            issues.Add(new HeaderTemplateIssue(
                "SOURCE_KEY_INVALID",
                "Opaque workbook and sheet keys cannot exceed 256 characters."));
        }

        if (headerRow is < 1 or > 1_048_576)
        {
            issues.Add(new HeaderTemplateIssue(
                "HEADER_ROW_INVALID",
                "The header row must be a positive spreadsheet row number."));
        }

        if (firstSourceColumn is < 1 or > 16_384)
        {
            issues.Add(new HeaderTemplateIssue(
                "HEADER_COLUMN_INVALID",
                "The first source column must be a positive spreadsheet column number."));
        }

        if (headers.Count is < 1 or > 128)
        {
            issues.Add(new HeaderTemplateIssue(
                "HEADER_WIDTH_INVALID",
                "Select between 1 and 128 contiguous header cells."));
        }
        else if (firstSourceColumn > 0
                 && firstSourceColumn + headers.Count - 1 > 16_384)
        {
            issues.Add(new HeaderTemplateIssue(
                "HEADER_RANGE_INVALID",
                "The selected header range exceeds the spreadsheet column limit."));
        }

        if (overrides is not null)
        {
            foreach (int ordinal in overrides.Keys)
            {
                if (ordinal < 0 || ordinal >= headers.Count)
                {
                    issues.Add(new HeaderTemplateIssue(
                        "HEADER_OVERRIDE_OUT_OF_RANGE",
                        "A header override refers to a column outside the selection.",
                        ordinal));
                }
            }
        }

        if (issues.Count > 0)
        {
            return new HeaderTemplateCreateResult(null, issues.AsReadOnly());
        }

        var mappedColumns = new List<HeaderColumnMapping>(headers.Count);
        var activeFieldIds = new HashSet<string>(StringComparer.Ordinal);
        for (int ordinal = 0; ordinal < headers.Count; ordinal++)
        {
            string original = headers[ordinal] ?? string.Empty;
            string normalized = DeterministicTextNormalizer.Normalize(original);
            if (original.Length > 256)
            {
                issues.Add(new HeaderTemplateIssue(
                    "HEADER_TOO_LONG",
                    "A header cell exceeds the 256-character limit.",
                    ordinal));
                continue;
            }

            HeaderMappingKind mappingKind;
            string? fieldId;
            if (overrides is not null
                && overrides.TryGetValue(ordinal, out HeaderMappingOverride? mappingOverride))
            {
                if (mappingOverride is null)
                {
                    mappingKind = HeaderMappingKind.Ignored;
                    fieldId = null;
                    issues.Add(new HeaderTemplateIssue(
                        "HEADER_OVERRIDE_INVALID",
                        "A header override is invalid.",
                        ordinal));
                }
                else
                {
                    mappingKind = mappingOverride.MappingKind;
                    fieldId = mappingOverride.FieldId;
                    ValidateOverride(
                        ordinal,
                        mappingOverride,
                        catalog,
                        issues);
                }
            }
            else
            {
                AliasMatch match = catalog.ResolveHeader(original);
                if (match.Status == AliasMatchStatus.Unique)
                {
                    mappingKind = HeaderMappingKind.Automatic;
                    fieldId = match.CanonicalFieldId;
                }
                else
                {
                    mappingKind = HeaderMappingKind.Ignored;
                    fieldId = null;
                    string code = match.Status == AliasMatchStatus.Ambiguous
                        ? "HEADER_AMBIGUOUS"
                        : "HEADER_UNKNOWN";
                    string message = match.Status == AliasMatchStatus.Ambiguous
                        ? "This header matches more than one canonical field and needs manual mapping."
                        : "This header is unknown and must be mapped or explicitly ignored.";
                    issues.Add(new HeaderTemplateIssue(code, message, ordinal));
                }
            }

            if (mappingKind != HeaderMappingKind.Ignored
                && !string.IsNullOrWhiteSpace(fieldId)
                && !activeFieldIds.Add(fieldId))
            {
                issues.Add(new HeaderTemplateIssue(
                    "DUPLICATE_FIELD_MAPPING",
                    $"The field '{fieldId}' is mapped by more than one header.",
                    ordinal));
            }

            mappedColumns.Add(new HeaderColumnMapping(
                ordinal,
                firstSourceColumn + ordinal,
                original,
                normalized,
                fieldId,
                mappingKind));
        }

        if (mappedColumns.All(column => column.MappingKind == HeaderMappingKind.Ignored))
        {
            issues.Add(new HeaderTemplateIssue(
                "NO_MAPPED_HEADERS",
                "At least one header must map to a canonical or custom field."));
        }

        if (issues.Count > 0)
        {
            return new HeaderTemplateCreateResult(null, issues.AsReadOnly());
        }

        var template = new HeaderTemplate(
            HeaderTemplate.CurrentSchemaVersion,
            Guid.NewGuid(),
            workbookKey,
            sheetKey,
            headerRow,
            firstSourceColumn,
            mappedColumns,
            HeaderFingerprint.Compute(headers),
            catalog.Version,
            createdAt ?? DateTimeOffset.UtcNow);
        return new HeaderTemplateCreateResult(template, Array.Empty<HeaderTemplateIssue>());
    }

    public static string CreateCustomFieldId(string header)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(header);
        string normalized = DeterministicTextNormalizer.Normalize(header);
        string hashInput = header
            .Normalize(NormalizationForm.FormKC)
            .Trim()
            .ToUpperInvariant();
        string slug = CreateAsciiSlug(normalized);
        slug = slug.Length > 32 ? slug[..32].TrimEnd('_') : slug;
        if (slug.Length == 0)
        {
            slug = "field";
        }

        string suffix = Convert.ToHexString(
            SHA256.HashData(Encoding.UTF8.GetBytes(hashInput)))[..8]
            .ToLowerInvariant();
        return $"custom.{slug}.{suffix}";
    }

    private static string CreateAsciiSlug(string normalizedHeader)
    {
        string decomposed = normalizedHeader.Normalize(NormalizationForm.FormD);
        var slug = new StringBuilder(decomposed.Length);
        bool pendingSeparator = false;
        foreach (char character in decomposed)
        {
            UnicodeCategory category = CharUnicodeInfo.GetUnicodeCategory(character);
            if (category is UnicodeCategory.NonSpacingMark
                or UnicodeCategory.SpacingCombiningMark
                or UnicodeCategory.EnclosingMark)
            {
                continue;
            }

            if (character is >= 'a' and <= 'z'
                || character is >= '0' and <= '9')
            {
                if (pendingSeparator && slug.Length > 0 && slug[^1] != '_')
                {
                    slug.Append('_');
                }

                slug.Append(character);
                pendingSeparator = false;
            }
            else
            {
                pendingSeparator = slug.Length > 0;
            }
        }

        return slug.ToString().TrimEnd('_');
    }

    private static void ValidateOverride(
        int ordinal,
        HeaderMappingOverride mappingOverride,
        CanonicalFieldCatalog catalog,
        List<HeaderTemplateIssue> issues)
    {
        if (mappingOverride.MappingKind == HeaderMappingKind.Automatic)
        {
            issues.Add(new HeaderTemplateIssue(
                "INVALID_OVERRIDE_KIND",
                "Explicit mappings must be manual, custom, or ignored.",
                ordinal));
            return;
        }

        if (mappingOverride.MappingKind == HeaderMappingKind.Ignored)
        {
            if (mappingOverride.FieldId is not null)
            {
                issues.Add(new HeaderTemplateIssue(
                    "IGNORED_FIELD_HAS_ID",
                    "An ignored header cannot have a field identifier.",
                    ordinal));
            }

            return;
        }

        if (string.IsNullOrWhiteSpace(mappingOverride.FieldId))
        {
            issues.Add(new HeaderTemplateIssue(
                "MAPPING_FIELD_REQUIRED",
                "A manual or custom mapping needs a field identifier.",
                ordinal));
            return;
        }

        if (mappingOverride.MappingKind == HeaderMappingKind.Manual
            && !catalog.TryGetDefinition(mappingOverride.FieldId, out _))
        {
            issues.Add(new HeaderTemplateIssue(
                "MAPPING_FIELD_UNKNOWN",
                $"The canonical field '{mappingOverride.FieldId}' is not defined.",
                ordinal));
        }

        if (mappingOverride.MappingKind == HeaderMappingKind.Custom
            && !IsValidCustomFieldId(mappingOverride.FieldId))
        {
            issues.Add(new HeaderTemplateIssue(
                "CUSTOM_FIELD_ID_INVALID",
                "Custom field identifiers must use custom.* with lowercase letters, digits, dots, or underscores.",
                ordinal));
        }
    }

    private static bool IsValidCustomFieldId(string fieldId)
    {
        return fieldId.StartsWith("custom.", StringComparison.Ordinal)
            && fieldId.Length <= 96
            && fieldId.All(character =>
                character is >= 'a' and <= 'z'
                || character is >= '0' and <= '9'
                || character is '_' or '.');
    }
}
