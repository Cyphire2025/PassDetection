namespace SmartCopyPaste.Core.Matching;

public sealed record FocusedFieldContext(
    string ProcessName,
    string ControlType,
    string AccessibleName = "",
    string AutomationId = "",
    string HelpText = "",
    string ClassName = "",
    bool IsPassword = false,
    bool IsReadOnly = false,
    bool IsEnabled = true,
    string? SavedCanonicalFieldId = null,
    string Placeholder = "",
    string SectionHeading = "",
    string InputType = "",
    string FormatHint = "");

public enum FieldMatchStatus
{
    Matched,
    Ambiguous,
    Unknown,
    Blocked,
    MissingValue,
}

public enum MatchEvidenceSource
{
    SavedMapping,
    AccessibleName,
    AutomationId,
    HelpText,
    Placeholder,
    SectionHeading,
    ContextualMetadata,
}

public sealed record FieldMatchEvidence(
    string CanonicalFieldId,
    MatchEvidenceSource Source,
    int Score,
    string Rule);

public sealed record FieldMatchResult(
    FieldMatchStatus Status,
    string? CanonicalFieldId,
    int Score,
    IReadOnlyList<FieldMatchEvidence> Evidence,
    string ReasonCode)
{
    public bool CanPaste =>
        Status == FieldMatchStatus.Matched
        && CanonicalFieldId is not null;
}

public enum FieldCandidateRankingStatus
{
    Ranked,
    NoRelatedCandidates,
    Blocked,
}

public enum FieldCandidateConfidence
{
    High,
    Medium,
    Low,
}

public sealed record RankedFieldCandidate(
    string CanonicalFieldId,
    string DisplayName,
    int Score,
    FieldCandidateConfidence Confidence,
    string ReasonCode,
    IReadOnlyList<FieldMatchEvidence> Evidence);

public sealed record FieldCandidateRankingResult(
    FieldCandidateRankingStatus Status,
    IReadOnlyList<RankedFieldCandidate> Candidates,
    string ReasonCode)
{
    public bool HasRelatedCandidates =>
        Status == FieldCandidateRankingStatus.Ranked
        && Candidates.Count > 0;
}

public enum TargetValueAdaptationStatus
{
    Unchanged,
    Adapted,
    Ambiguous,
    Invalid,
}

public enum TargetValueAdaptationKind
{
    None,
    Uppercase,
    Lowercase,
    DateFormat,
    PhoneDigitsOnly,
    PhoneCompactInternational,
}

public sealed record TargetValueAdaptationResult(
    TargetValueAdaptationStatus Status,
    string Value,
    TargetValueAdaptationKind Adaptation,
    string ReasonCode)
{
    public bool IsSafeToPaste =>
        Status is TargetValueAdaptationStatus.Unchanged
            or TargetValueAdaptationStatus.Adapted;
}
