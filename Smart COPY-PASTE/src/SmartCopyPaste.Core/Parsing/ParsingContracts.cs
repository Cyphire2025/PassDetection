using System.Collections.ObjectModel;
using SmartCopyPaste.Core.Session;

namespace SmartCopyPaste.Core.Parsing;

public enum ParseIssueSeverity
{
    Warning,
    Error,
}

public sealed record ParseIssue(
    string Code,
    string Message,
    ParseIssueSeverity Severity = ParseIssueSeverity.Error,
    int? Row = null,
    int? Column = null);

public sealed record TabularParseResult(
    IReadOnlyList<IReadOnlyList<string>> Rows,
    IReadOnlyList<ParseIssue> Issues)
{
    public bool Success => Issues.All(issue => issue.Severity != ParseIssueSeverity.Error);

    public int MaximumColumnCount =>
        Rows.Count == 0 ? 0 : Rows.Max(row => row.Count);
}

public enum PassengerParseMode
{
    SavedHeaderRows,
    HeaderAndRows,
    VerticalKeyValue,
}

public sealed record PassengerParseResult(
    PassengerParseMode Mode,
    IReadOnlyList<PassengerProfile> Profiles,
    IReadOnlyList<ParseIssue> Issues)
{
    public bool Success =>
        Profiles.Count > 0
        && Issues.All(issue => issue.Severity != ParseIssueSeverity.Error);
}

public sealed record TabularDataParserOptions(
    int MaxInputCharacters = 262_144,
    int MaxRows = 100,
    int MaxColumns = 128,
    int MaxCellCharacters = 2_048,
    int MaxTotalCells = 12_800)
{
    public static TabularDataParserOptions Default { get; } = new();

    internal void Validate()
    {
        ArgumentOutOfRangeException.ThrowIfLessThan(MaxInputCharacters, 1);
        ArgumentOutOfRangeException.ThrowIfLessThan(MaxRows, 1);
        ArgumentOutOfRangeException.ThrowIfLessThan(MaxColumns, 1);
        ArgumentOutOfRangeException.ThrowIfLessThan(MaxCellCharacters, 1);
        ArgumentOutOfRangeException.ThrowIfLessThan(MaxTotalCells, 1);
        if (MaxTotalCells < MaxRows)
        {
            throw new ArgumentOutOfRangeException(
                nameof(MaxTotalCells),
                "The total-cell limit cannot be lower than the row limit.");
        }
    }

    internal static IReadOnlyList<IReadOnlyList<string>> FreezeRows(
        IEnumerable<List<string>> rows)
    {
        return new ReadOnlyCollection<IReadOnlyList<string>>(
            rows.Select(row =>
                    (IReadOnlyList<string>)Array.AsReadOnly(row.ToArray()))
                .ToArray());
    }
}
