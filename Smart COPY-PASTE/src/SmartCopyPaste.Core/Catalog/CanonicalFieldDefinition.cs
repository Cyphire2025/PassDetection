namespace SmartCopyPaste.Core.Catalog;

public enum CanonicalFieldValueKind
{
    Text,
    Name,
    Date,
    Email,
    Phone,
    Country,
    Nationality,
    Gender,
    Identifier,
    Address,
    Number,
}

public enum CanonicalFieldSensitivity
{
    Personal,
    Sensitive,
    HighlySensitive,
}

public sealed record CanonicalFieldDefinition(
    string Id,
    string DisplayName,
    string FieldGroup,
    CanonicalFieldValueKind ValueKind,
    CanonicalFieldSensitivity Sensitivity,
    IReadOnlyList<string> SourceAliases,
    IReadOnlyList<string> TargetAliases,
    IReadOnlyList<string> BlockingTargetTokens);

public enum AliasMatchStatus
{
    Unknown,
    Unique,
    Ambiguous,
}

public sealed record AliasMatch(
    AliasMatchStatus Status,
    string NormalizedInput,
    string? CanonicalFieldId,
    IReadOnlyList<string> CandidateFieldIds)
{
    public bool IsMatch => Status == AliasMatchStatus.Unique && CanonicalFieldId is not null;
}
