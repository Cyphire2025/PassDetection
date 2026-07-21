using System.Text;
using SmartCopyPaste.Core.Catalog;
using SmartCopyPaste.Core.Headers;
using SmartCopyPaste.Core.Session;

namespace SmartCopyPaste.Core.Parsing;

/// <summary>
/// Bounded deterministic parser for Excel-style tab-separated clipboard data.
/// It never infers a saved header template from width alone.
/// </summary>
public sealed class TabularDataParser
{
    private readonly CanonicalFieldCatalog _catalog;
    private readonly TabularDataParserOptions _options;

    public TabularDataParser(
        CanonicalFieldCatalog? catalog = null,
        TabularDataParserOptions? options = null)
    {
        _catalog = catalog ?? CanonicalFieldCatalog.Default;
        _options = options ?? TabularDataParserOptions.Default;
        _options.Validate();
    }

    /// <summary>
    /// Parses a raw TSV matrix and preserves empty cells, including trailing cells.
    /// </summary>
    public TabularParseResult Parse(string input)
    {
        ArgumentNullException.ThrowIfNull(input);
        if (input.Length == 0)
        {
            return FailedTable("EMPTY_INPUT", "The copied selection is empty.");
        }

        if (input.Length > _options.MaxInputCharacters)
        {
            return FailedTable(
                "INPUT_TOO_LARGE",
                $"The copied selection exceeds {_options.MaxInputCharacters} characters.");
        }

        var rows = new List<List<string>>();
        var currentRow = new List<string>();
        var currentCell = new StringBuilder();
        bool inQuotes = false;
        bool quoteClosed = false;
        bool atCellStart = true;
        bool endedWithRowSeparator = false;
        int totalCells = 0;

        for (int index = 0; index < input.Length; index++)
        {
            char character = input[index];
            if (character == '\0')
            {
                return FailedTable(
                    "INVALID_CONTROL_CHARACTER",
                    "The copied selection contains an unsupported null character.");
            }

            if (inQuotes)
            {
                if (character == '"')
                {
                    if (index + 1 < input.Length && input[index + 1] == '"')
                    {
                        currentCell.Append('"');
                        index++;
                    }
                    else
                    {
                        inQuotes = false;
                        quoteClosed = true;
                    }
                }
                else if (character == '\r')
                {
                    if (index + 1 < input.Length && input[index + 1] == '\n')
                    {
                        index++;
                    }

                    currentCell.Append('\n');
                }
                else
                {
                    currentCell.Append(character);
                }

                if (currentCell.Length > _options.MaxCellCharacters)
                {
                    return FailedTable(
                        "CELL_TOO_LARGE",
                        $"A copied cell exceeds {_options.MaxCellCharacters} characters.");
                }

                continue;
            }

            bool isRowSeparator = character is '\r' or '\n';
            if (quoteClosed && character != '\t' && !isRowSeparator)
            {
                return FailedTable(
                    "MALFORMED_TSV",
                    "Unexpected text appears after a quoted clipboard cell.");
            }

            if (atCellStart && character == '"')
            {
                inQuotes = true;
                atCellStart = false;
                endedWithRowSeparator = false;
                continue;
            }

            if (character == '\t')
            {
                if (!TryCommitCell(
                    currentRow,
                    currentCell,
                    ref totalCells,
                    out ParseIssue? issue))
                {
                    return FailedTable(issue);
                }

                atCellStart = true;
                quoteClosed = false;
                endedWithRowSeparator = false;
                continue;
            }

            if (isRowSeparator)
            {
                if (character == '\r'
                    && index + 1 < input.Length
                    && input[index + 1] == '\n')
                {
                    index++;
                }

                if (!TryCommitCell(
                    currentRow,
                    currentCell,
                    ref totalCells,
                    out ParseIssue? cellIssue))
                {
                    return FailedTable(cellIssue);
                }

                if (!TryCommitRow(rows, currentRow, out ParseIssue? rowIssue))
                {
                    return FailedTable(rowIssue);
                }

                currentRow = [];
                atCellStart = true;
                quoteClosed = false;
                endedWithRowSeparator = true;
                continue;
            }

            currentCell.Append(character);
            if (currentCell.Length > _options.MaxCellCharacters)
            {
                return FailedTable(
                    "CELL_TOO_LARGE",
                    $"A copied cell exceeds {_options.MaxCellCharacters} characters.");
            }

            atCellStart = false;
            endedWithRowSeparator = false;
        }

        if (inQuotes)
        {
            return FailedTable(
                "MALFORMED_TSV",
                "A quoted clipboard cell was not closed.");
        }

        if (!endedWithRowSeparator || currentRow.Count > 0 || currentCell.Length > 0)
        {
            if (!TryCommitCell(
                currentRow,
                currentCell,
                ref totalCells,
                out ParseIssue? cellIssue))
            {
                return FailedTable(cellIssue);
            }

            if (!TryCommitRow(rows, currentRow, out ParseIssue? rowIssue))
            {
                return FailedTable(rowIssue);
            }
        }

        if (rows.Count == 0)
        {
            return FailedTable("EMPTY_INPUT", "The copied selection is empty.");
        }

        return new TabularParseResult(
            TabularDataParserOptions.FreezeRows(rows),
            Array.Empty<ParseIssue>());
    }

    public PassengerParseResult Parse(
        string input,
        HeaderTemplate savedHeaderTemplate) =>
        ParseRows(input, savedHeaderTemplate);

    public PassengerParseResult ParseRows(
        string input,
        HeaderTemplate savedHeaderTemplate)
    {
        ArgumentNullException.ThrowIfNull(savedHeaderTemplate);
        TabularParseResult table = Parse(input);
        if (!table.Success)
        {
            return FailedProfiles(PassengerParseMode.SavedHeaderRows, table.Issues);
        }

        if (table.Rows.Count > _options.MaxRows)
        {
            return FailedProfiles(
                PassengerParseMode.SavedHeaderRows,
                Issue("TOO_MANY_PASSENGERS", "Too many passenger rows were selected."));
        }

        int expectedWidth = savedHeaderTemplate.Columns.Count;
        var issues = ValidateWidths(table.Rows, expectedWidth);
        if (issues.Count > 0)
        {
            return FailedProfiles(PassengerParseMode.SavedHeaderRows, issues);
        }

        IReadOnlyList<string> expectedHeaders = savedHeaderTemplate.Columns
            .Select(column => column.OriginalHeader)
            .ToArray();
        var profiles = new List<PassengerProfile>(table.Rows.Count);
        for (int rowIndex = 0; rowIndex < table.Rows.Count; rowIndex++)
        {
            IReadOnlyList<string> row = table.Rows[rowIndex];
            if (HeaderFingerprint.Compute(row)
                == HeaderFingerprint.Compute(expectedHeaders)
                || LooksLikeHeaderRow(row, savedHeaderTemplate.Columns))
            {
                issues.Add(Issue(
                    "HEADER_INCLUDED_AS_PASSENGER",
                    "Copy passenger rows only; the saved header row was included.",
                    rowIndex + 1));
                continue;
            }

            PassengerProfile? profile = CreateProfile(
                row,
                savedHeaderTemplate.Columns,
                rowIndex + 1,
                savedHeaderTemplate.TemplateId,
                issues);
            if (profile is not null)
            {
                profiles.Add(profile);
            }
        }

        return CreateProfileResult(
            PassengerParseMode.SavedHeaderRows,
            profiles,
            issues);
    }

    public PassengerParseResult ParseDirect(string input)
    {
        TabularParseResult table = Parse(input);
        if (!table.Success)
        {
            return FailedProfiles(PassengerParseMode.HeaderAndRows, table.Issues);
        }

        bool verticalCandidate = IsVerticalCandidate(table.Rows);
        bool horizontalCandidate = IsHorizontalCandidate(table.Rows);
        if (verticalCandidate && horizontalCandidate)
        {
            return FailedProfiles(
                PassengerParseMode.HeaderAndRows,
                Issue(
                    "AMBIGUOUS_LAYOUT",
                    "The copied selection could be interpreted as either horizontal or vertical data."));
        }

        if (verticalCandidate)
        {
            return ParseVerticalRows(table.Rows);
        }

        if (horizontalCandidate)
        {
            return ParseHeaderRows(table.Rows);
        }

        return FailedProfiles(
            PassengerParseMode.HeaderAndRows,
            Issue(
                "HEADER_NOT_IDENTIFIED",
                "Smart Copy could not identify a deterministic header row."));
    }

    public PassengerParseResult ParseHeaderAndRows(string input)
    {
        TabularParseResult table = Parse(input);
        return table.Success
            ? ParseHeaderRows(table.Rows)
            : FailedProfiles(PassengerParseMode.HeaderAndRows, table.Issues);
    }

    public PassengerParseResult ParseVerticalKeyValues(string input)
    {
        TabularParseResult table = Parse(input);
        return table.Success
            ? ParseVerticalRows(table.Rows)
            : FailedProfiles(PassengerParseMode.VerticalKeyValue, table.Issues);
    }

    private PassengerParseResult ParseHeaderRows(
        IReadOnlyList<IReadOnlyList<string>> rows)
    {
        if (rows.Count < 2)
        {
            return FailedProfiles(
                PassengerParseMode.HeaderAndRows,
                Issue(
                    "PASSENGER_ROW_REQUIRED",
                    "Copy the header row and at least one passenger row."));
        }

        IReadOnlyList<string> headers = rows[0];
        if (headers.Count > _options.MaxColumns)
        {
            return FailedProfiles(
                PassengerParseMode.HeaderAndRows,
                Issue("TOO_MANY_COLUMNS", "The copied selection contains too many columns."));
        }

        var issues = new List<ParseIssue>();
        HeaderColumnMapping[] mappings = ResolveDirectMappings(headers, issues);
        issues.AddRange(ValidateWidths(rows.Skip(1).ToArray(), headers.Count, 2));
        if (issues.Any(issue => issue.Severity == ParseIssueSeverity.Error))
        {
            return FailedProfiles(PassengerParseMode.HeaderAndRows, issues);
        }

        string headerFingerprint = HeaderFingerprint.Compute(headers);
        var profiles = new List<PassengerProfile>();
        for (int rowIndex = 1; rowIndex < rows.Count; rowIndex++)
        {
            IReadOnlyList<string> row = rows[rowIndex];
            if (HeaderFingerprint.Compute(row) == headerFingerprint
                || LooksLikeHeaderRow(row, mappings))
            {
                issues.Add(Issue(
                    "HEADER_INCLUDED_AS_PASSENGER",
                    "A header row appears where passenger data was expected.",
                    rowIndex + 1));
                continue;
            }

            PassengerProfile? profile = CreateProfile(
                row,
                mappings,
                rowIndex + 1,
                null,
                issues);
            if (profile is not null)
            {
                profiles.Add(profile);
            }
        }

        return CreateProfileResult(
            PassengerParseMode.HeaderAndRows,
            profiles,
            issues);
    }

    private PassengerParseResult ParseVerticalRows(
        IReadOnlyList<IReadOnlyList<string>> rows)
    {
        var issues = ValidateWidths(rows, 2);
        if (issues.Count > 0)
        {
            return FailedProfiles(PassengerParseMode.VerticalKeyValue, issues);
        }

        var fields = new Dictionary<string, string>(StringComparer.Ordinal);
        for (int rowIndex = 0; rowIndex < rows.Count; rowIndex++)
        {
            IReadOnlyList<string> row = rows[rowIndex];
            AliasMatch match = _catalog.ResolveHeader(row[0]);
            if (match.Status == AliasMatchStatus.Unknown)
            {
                issues.Add(Issue(
                    "HEADER_UNKNOWN",
                    "A vertical key is not a recognized canonical header.",
                    rowIndex + 1,
                    1));
                continue;
            }

            if (match.Status == AliasMatchStatus.Ambiguous
                || match.CanonicalFieldId is null)
            {
                issues.Add(Issue(
                    "HEADER_AMBIGUOUS",
                    "A vertical key matches more than one canonical field.",
                    rowIndex + 1,
                    1));
                continue;
            }

            if (fields.ContainsKey(match.CanonicalFieldId))
            {
                issues.Add(Issue(
                    "DUPLICATE_FIELD",
                    $"The field '{match.CanonicalFieldId}' appears more than once.",
                    rowIndex + 1,
                    1));
                continue;
            }

            string value = CleanValue(row[1]);
            if (value.Length > 0)
            {
                fields.Add(match.CanonicalFieldId, value);
            }
        }

        if (issues.Any(issue => issue.Severity == ParseIssueSeverity.Error))
        {
            return FailedProfiles(PassengerParseMode.VerticalKeyValue, issues);
        }

        if (fields.Count == 0)
        {
            return FailedProfiles(
                PassengerParseMode.VerticalKeyValue,
                Issue(
                    "EMPTY_PASSENGER_ROW",
                    "The vertical selection does not contain any passenger values."));
        }

        PassengerProfile profile = PassengerProfile.Create(fields, sourceRowNumber: 1);
        return new PassengerParseResult(
            PassengerParseMode.VerticalKeyValue,
            Array.AsReadOnly([profile]),
            Array.Empty<ParseIssue>());
    }

    private HeaderColumnMapping[] ResolveDirectMappings(
        IReadOnlyList<string> headers,
        List<ParseIssue> issues)
    {
        var mappings = new HeaderColumnMapping[headers.Count];
        var fieldIds = new HashSet<string>(StringComparer.Ordinal);
        for (int ordinal = 0; ordinal < headers.Count; ordinal++)
        {
            string header = headers[ordinal];
            AliasMatch match = _catalog.ResolveHeader(header);
            string? fieldId = match.CanonicalFieldId;
            if (match.Status == AliasMatchStatus.Unknown)
            {
                issues.Add(Issue(
                    "HEADER_UNKNOWN",
                    "A copied header is not recognized; save and map this header first.",
                    1,
                    ordinal + 1));
            }
            else if (match.Status == AliasMatchStatus.Ambiguous || fieldId is null)
            {
                issues.Add(Issue(
                    "HEADER_AMBIGUOUS",
                    "A copied header matches more than one canonical field.",
                    1,
                    ordinal + 1));
            }
            else if (!fieldIds.Add(fieldId))
            {
                issues.Add(Issue(
                    "DUPLICATE_FIELD",
                    $"The field '{fieldId}' is represented by more than one header.",
                    1,
                    ordinal + 1));
            }

            mappings[ordinal] = new HeaderColumnMapping(
                ordinal,
                ordinal + 1,
                header,
                match.NormalizedInput,
                fieldId,
                HeaderMappingKind.Automatic);
        }

        return mappings;
    }

    private static PassengerProfile? CreateProfile(
        IReadOnlyList<string> row,
        IReadOnlyList<HeaderColumnMapping> mappings,
        int sourceRow,
        Guid? templateId,
        List<ParseIssue> issues)
    {
        var fields = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (HeaderColumnMapping mapping in mappings)
        {
            if (mapping.MappingKind == HeaderMappingKind.Ignored
                || mapping.FieldId is null)
            {
                continue;
            }

            string value = CleanValue(row[mapping.Ordinal]);
            if (value.Length == 0)
            {
                continue;
            }

            if (!fields.TryAdd(mapping.FieldId, value))
            {
                issues.Add(Issue(
                    "DUPLICATE_FIELD",
                    $"The field '{mapping.FieldId}' is mapped more than once.",
                    sourceRow,
                    mapping.Ordinal + 1));
                return null;
            }
        }

        if (fields.Count == 0)
        {
            issues.Add(Issue(
                "EMPTY_PASSENGER_ROW",
                "A selected passenger row does not contain any mapped values.",
                sourceRow));
            return null;
        }

        return PassengerProfile.Create(fields, sourceRow, templateId);
    }

    private bool IsVerticalCandidate(
        IReadOnlyList<IReadOnlyList<string>> rows)
    {
        if (rows.Count == 0 || rows.Any(row => row.Count != 2))
        {
            return false;
        }

        return rows.All(row => _catalog.ResolveHeader(row[0]).Status != AliasMatchStatus.Unknown);
    }

    private bool LooksLikeHeaderRow(
        IReadOnlyList<string> row,
        IReadOnlyList<HeaderColumnMapping> mappings)
    {
        bool examinedMappedColumn = false;
        foreach (HeaderColumnMapping mapping in mappings)
        {
            if (mapping.MappingKind == HeaderMappingKind.Ignored
                || mapping.FieldId is null)
            {
                continue;
            }

            examinedMappedColumn = true;
            if (mapping.MappingKind == HeaderMappingKind.Custom)
            {
                if (!string.Equals(
                    SmartCopyPaste.Core.Normalization.DeterministicTextNormalizer.Normalize(
                        row[mapping.Ordinal]),
                    mapping.NormalizedHeader,
                    StringComparison.Ordinal))
                {
                    return false;
                }

                continue;
            }

            AliasMatch match = _catalog.ResolveHeader(row[mapping.Ordinal]);
            if (match.Status != AliasMatchStatus.Unique
                || !string.Equals(
                    match.CanonicalFieldId,
                    mapping.FieldId,
                    StringComparison.Ordinal))
            {
                return false;
            }
        }

        return examinedMappedColumn;
    }

    private bool IsHorizontalCandidate(
        IReadOnlyList<IReadOnlyList<string>> rows)
    {
        if (rows.Count < 2 || rows[0].Count == 0)
        {
            return false;
        }

        return rows[0]
            .Select(_catalog.ResolveHeader)
            .All(match => match.Status != AliasMatchStatus.Unknown);
    }

    private static List<ParseIssue> ValidateWidths(
        IReadOnlyList<IReadOnlyList<string>> rows,
        int expectedWidth,
        int startingRow = 1)
    {
        var issues = new List<ParseIssue>();
        for (int rowIndex = 0; rowIndex < rows.Count; rowIndex++)
        {
            if (rows[rowIndex].Count != expectedWidth)
            {
                issues.Add(Issue(
                    "WIDTH_MISMATCH",
                    $"Expected {expectedWidth} cells but found {rows[rowIndex].Count}.",
                    rowIndex + startingRow));
            }
        }

        return issues;
    }

    private bool TryCommitCell(
        List<string> row,
        StringBuilder cell,
        ref int totalCells,
        out ParseIssue? issue)
    {
        if (row.Count >= _options.MaxColumns)
        {
            issue = Issue(
                "TOO_MANY_COLUMNS",
                $"The copied selection exceeds {_options.MaxColumns} columns.");
            return false;
        }

        totalCells++;
        if (totalCells > _options.MaxTotalCells)
        {
            issue = Issue(
                "TOO_MANY_CELLS",
                $"The copied selection exceeds {_options.MaxTotalCells} cells.");
            return false;
        }

        row.Add(cell.ToString());
        cell.Clear();
        issue = null;
        return true;
    }

    private bool TryCommitRow(
        List<List<string>> rows,
        List<string> row,
        out ParseIssue? issue)
    {
        if (rows.Count >= _options.MaxRows)
        {
            issue = Issue(
                "TOO_MANY_ROWS",
                $"The copied selection exceeds {_options.MaxRows} rows.");
            return false;
        }

        rows.Add(row);
        issue = null;
        return true;
    }

    private static string CleanValue(string value) => value.Trim();

    private static PassengerParseResult CreateProfileResult(
        PassengerParseMode mode,
        List<PassengerProfile> profiles,
        List<ParseIssue> issues)
    {
        return new PassengerParseResult(
            mode,
            profiles.AsReadOnly(),
            issues.AsReadOnly());
    }

    private static TabularParseResult FailedTable(string code, string message) =>
        FailedTable(Issue(code, message));

    private static TabularParseResult FailedTable(ParseIssue? issue)
    {
        return new TabularParseResult(
            Array.Empty<IReadOnlyList<string>>(),
            issue is null ? Array.Empty<ParseIssue>() : Array.AsReadOnly([issue]));
    }

    private static PassengerParseResult FailedProfiles(
        PassengerParseMode mode,
        ParseIssue issue) =>
        FailedProfiles(mode, Array.AsReadOnly([issue]));

    private static PassengerParseResult FailedProfiles(
        PassengerParseMode mode,
        IReadOnlyList<ParseIssue> issues)
    {
        return new PassengerParseResult(
            mode,
            Array.Empty<PassengerProfile>(),
            Array.AsReadOnly(issues.ToArray()));
    }

    private static ParseIssue Issue(
        string code,
        string message,
        int? row = null,
        int? column = null) =>
        new(code, message, ParseIssueSeverity.Error, row, column);
}
