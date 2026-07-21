using SmartCopyPaste.Core.Matching;

namespace SmartCopyPaste.Core.Tests;

public sealed class FocusedFieldMatcherTests
{
    private static readonly string[] Available =
    [
        "personal.surname",
        "personal.given_name",
        "passport.number",
        "passport.issue_date",
        "passport.expiry_date",
        "identity.national_id_number",
        "contact.email",
    ];

    private readonly FocusedFieldMatcher _matcher = new();

    [Fact]
    public void ExactAccessibleName_PastesAtHighConfidence()
    {
        var context = Context(accessibleName: "Passport Number");

        FieldMatchResult result = _matcher.Match(context, Available);

        Assert.True(result.CanPaste);
        Assert.Equal(FieldMatchStatus.Matched, result.Status);
        Assert.Equal("passport.number", result.CanonicalFieldId);
        Assert.Equal(95, result.Score);
        Assert.Contains(
            result.Evidence,
            evidence => evidence.Source == MatchEvidenceSource.AccessibleName);
    }

    [Fact]
    public void CamelCaseAutomationId_IsNormalizedAndCanMatch()
    {
        var context = Context(automationId: "passportNumber");

        FieldMatchResult result = _matcher.Match(context, Available);

        Assert.Equal(FieldMatchStatus.Matched, result.Status);
        Assert.Equal("passport.number", result.CanonicalFieldId);
        Assert.Equal(90, result.Score);
    }

    [Fact]
    public void ConsistentExactSignals_GetDeterministicBonus()
    {
        var context = Context(
            accessibleName: "Surname",
            automationId: "familyName");

        FieldMatchResult first = _matcher.Match(context, Available);
        FieldMatchResult second = _matcher.Match(
            context,
            Available.Reverse());

        Assert.Equal(FieldMatchStatus.Matched, first.Status);
        Assert.Equal("personal.surname", first.CanonicalFieldId);
        Assert.Equal(97, first.Score);
        Assert.Equal(first.Status, second.Status);
        Assert.Equal(first.CanonicalFieldId, second.CanonicalFieldId);
        Assert.Equal(first.Score, second.Score);
        Assert.Equal(first.ReasonCode, second.ReasonCode);
        Assert.Equal(first.Evidence, second.Evidence);
    }

    [Fact]
    public void HelpTextAlone_RequiresManualConfirmation()
    {
        var context = Context(helpText: "Email Address");

        FieldMatchResult result = _matcher.Match(context, Available);

        Assert.Equal(FieldMatchStatus.Unknown, result.Status);
        Assert.Equal("contact.email", result.CanonicalFieldId);
        Assert.Equal(80, result.Score);
        Assert.False(result.CanPaste);
    }

    [Fact]
    public void SavedMapping_HasPrecedenceOverConflictingMetadata()
    {
        var context = Context(
            accessibleName: "Surname",
            savedCanonicalFieldId: "passport.number");

        FieldMatchResult result = _matcher.Match(context, Available);

        Assert.Equal(FieldMatchStatus.Matched, result.Status);
        Assert.Equal("passport.number", result.CanonicalFieldId);
        Assert.Equal(100, result.Score);
        Assert.Equal("SAVED_MAPPING", result.ReasonCode);
        Assert.Single(result.Evidence);
    }

    [Fact]
    public void SavedMapping_DoesNotPasteWhenProfileLacksValue()
    {
        var context = Context(savedCanonicalFieldId: "passport.number");

        FieldMatchResult result = _matcher.Match(
            context,
            new[] { "personal.surname" });

        Assert.Equal(FieldMatchStatus.MissingValue, result.Status);
        Assert.Equal("passport.number", result.CanonicalFieldId);
        Assert.False(result.CanPaste);
    }

    [Fact]
    public void ConflictingStrongSignals_AreBlockedAsAmbiguous()
    {
        var context = Context(
            accessibleName: "Surname",
            automationId: "GivenName");

        FieldMatchResult result = _matcher.Match(context, Available);

        Assert.Equal(FieldMatchStatus.Ambiguous, result.Status);
        Assert.Null(result.CanonicalFieldId);
        Assert.Equal("MATCH_SCORE_NOT_UNIQUE", result.ReasonCode);
    }

    [Fact]
    public void PassportLabelWithApplicationIdentifier_IsBlocked()
    {
        var context = Context(
            accessibleName: "Passport Number",
            automationId: "applicationNumber");

        FieldMatchResult result = _matcher.Match(context, Available);

        Assert.Equal(FieldMatchStatus.Ambiguous, result.Status);
        Assert.Equal("CONFLICTING_TARGET_TOKEN", result.ReasonCode);
        Assert.False(result.CanPaste);
    }

    [Theory]
    [InlineData("Document Number")]
    [InlineData("Issue Date")]
    [InlineData("Expiry Date")]
    [InlineData("Application Number")]
    [InlineData("Visa Number")]
    [InlineData("Booking Ref")]
    public void UnsafeGenericOrNonPassengerLabels_OpenPicker(string accessibleName)
    {
        FieldMatchResult result = _matcher.Match(
            Context(accessibleName: accessibleName),
            Available);

        Assert.Equal(FieldMatchStatus.Unknown, result.Status);
        Assert.False(result.CanPaste);
    }

    [Fact]
    public void NationalId_DoesNotConfusePassportNumber()
    {
        FieldMatchResult result = _matcher.Match(
            Context(accessibleName: "National ID Number"),
            Available);

        Assert.Equal(FieldMatchStatus.Matched, result.Status);
        Assert.Equal("identity.national_id_number", result.CanonicalFieldId);
    }

    [Theory]
    [InlineData(true, false, true, "PASSWORD_CONTROL")]
    [InlineData(false, true, true, "CONTROL_READ_ONLY")]
    [InlineData(false, false, false, "CONTROL_DISABLED")]
    public void ProtectedControls_AreBlocked(
        bool isPassword,
        bool isReadOnly,
        bool isEnabled,
        string reason)
    {
        var context = new FocusedFieldContext(
            "chrome.exe",
            "Edit",
            "Passport Number",
            "",
            "",
            "",
            isPassword,
            isReadOnly,
            isEnabled);

        FieldMatchResult result = _matcher.Match(context, Available);

        Assert.Equal(FieldMatchStatus.Blocked, result.Status);
        Assert.Equal(reason, result.ReasonCode);
    }

    [Fact]
    public void ExactMatchWithoutAvailableProfileValue_DoesNotPaste()
    {
        FieldMatchResult result = _matcher.Match(
            Context(accessibleName: "Passport Number"),
            new[] { "personal.surname" });

        Assert.Equal(FieldMatchStatus.MissingValue, result.Status);
        Assert.Equal("passport.number", result.CanonicalFieldId);
    }

    [Fact]
    public void OversizedUntrustedFieldMetadata_IsBlockedBeforeMatching()
    {
        FieldMatchResult result = _matcher.Match(
            Context(accessibleName: new string('A', 513)),
            Available);

        Assert.Equal(FieldMatchStatus.Blocked, result.Status);
        Assert.Equal("FIELD_METADATA_TOO_LARGE", result.ReasonCode);
    }

    private static FocusedFieldContext Context(
        string accessibleName = "",
        string automationId = "",
        string helpText = "",
        string? savedCanonicalFieldId = null) =>
        new(
            "chrome.exe",
            "Edit",
            accessibleName,
            automationId,
            helpText,
            "Chrome_RenderWidgetHostHWND",
            IsPassword: false,
            IsReadOnly: false,
            IsEnabled: true,
            SavedCanonicalFieldId: savedCanonicalFieldId);
}
