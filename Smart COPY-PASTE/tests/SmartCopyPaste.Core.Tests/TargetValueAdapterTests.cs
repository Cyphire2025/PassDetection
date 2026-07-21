using SmartCopyPaste.Core.Matching;

namespace SmartCopyPaste.Core.Tests;

public sealed class TargetValueAdapterTests
{
    private readonly TargetValueAdapter _adapter = new();

    [Theory]
    [InlineData("SURNAME")]
    [InlineData("Surname")]
    [InlineData("surname")]
    public void LabelCapitalizationAlone_DoesNotTransformValue(string label)
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "personal.surname",
            "McDonald",
            Context(accessibleName: label));

        Assert.Equal(TargetValueAdaptationStatus.Unchanged, result.Status);
        Assert.Equal(TargetValueAdaptationKind.None, result.Adaptation);
        Assert.Equal("McDonald", result.Value);
        Assert.True(result.IsSafeToPaste);
    }

    [Theory]
    [InlineData("UPPERCASE", "McDonald", "MCDONALD", TargetValueAdaptationKind.Uppercase)]
    [InlineData("lower case", "McDonald", "mcdonald", TargetValueAdaptationKind.Lowercase)]
    [InlineData("capital letters only", "ab123", "AB123", TargetValueAdaptationKind.Uppercase)]
    public void ExplicitCaseRequirement_IsAppliedInvariantly(
        string formatHint,
        string value,
        string expected,
        TargetValueAdaptationKind expectedKind)
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "passport.number",
            value,
            Context(formatHint: formatHint));

        Assert.Equal(TargetValueAdaptationStatus.Adapted, result.Status);
        Assert.Equal(expectedKind, result.Adaptation);
        Assert.Equal(expected, result.Value);
        Assert.True(result.IsSafeToPaste);
    }

    [Fact]
    public void ConflictingCaseRequirements_AreNotGuessed()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "passport.number",
            "ab123",
            Context(formatHint: "Uppercase or lowercase"));

        Assert.Equal(TargetValueAdaptationStatus.Ambiguous, result.Status);
        Assert.Equal("ab123", result.Value);
        Assert.False(result.IsSafeToPaste);
    }

    [Theory]
    [InlineData("Do not use capital letters")]
    [InlineData("Uppercase is not allowed")]
    public void NegatedCaseRequirement_IsNotApplied(string formatHint)
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "passport.number",
            "ab123",
            Context(formatHint: formatHint));

        Assert.Equal(TargetValueAdaptationStatus.Ambiguous, result.Status);
        Assert.Equal("ab123", result.Value);
        Assert.False(result.IsSafeToPaste);
    }

    [Theory]
    [InlineData("DD/MM/YYYY", "04/07/2025")]
    [InlineData("DD-MM-YYYY", "04-07-2025")]
    [InlineData("MM/DD/YYYY", "07/04/2025")]
    [InlineData("DD MMM YYYY", "04 Jul 2025")]
    public void ExplicitDateFormat_ConvertsUnambiguousIsoSource(
        string formatHint,
        string expected)
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "personal.date_of_birth",
            "2025-07-04",
            Context(formatHint: formatHint));

        Assert.Equal(TargetValueAdaptationStatus.Adapted, result.Status);
        Assert.Equal(TargetValueAdaptationKind.DateFormat, result.Adaptation);
        Assert.Equal(expected, result.Value);
        Assert.True(result.IsSafeToPaste);
    }

    [Fact]
    public void NativeDateInput_IsOutsideTheTextPasteContract()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "passport.expiry_date",
            "2032-01-09",
            Context(inputType: "date"));

        Assert.Equal(TargetValueAdaptationStatus.Ambiguous, result.Status);
        Assert.Equal("2032-01-09", result.Value);
        Assert.False(result.IsSafeToPaste);
    }

    [Fact]
    public void ConflictingDateFormats_AreNotGuessed()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "personal.date_of_birth",
            "2025-07-04",
            Context(formatHint: "DD/MM/YYYY or MM/DD/YYYY"));

        Assert.Equal(TargetValueAdaptationStatus.Ambiguous, result.Status);
        Assert.Equal("2025-07-04", result.Value);
        Assert.False(result.IsSafeToPaste);
    }

    [Fact]
    public void NegatedDateFormat_IsNotApplied()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "personal.date_of_birth",
            "2025-07-04",
            Context(formatHint: "Do not use DD/MM/YYYY"));

        Assert.Equal(TargetValueAdaptationStatus.Ambiguous, result.Status);
        Assert.Equal("2025-07-04", result.Value);
        Assert.False(result.IsSafeToPaste);
    }

    [Fact]
    public void AmbiguousSourceDate_IsNotReinterpreted()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "personal.date_of_birth",
            "04/05/2025",
            Context(formatHint: "DD-MM-YYYY"));

        Assert.Equal(TargetValueAdaptationStatus.Ambiguous, result.Status);
        Assert.Equal("04/05/2025", result.Value);
        Assert.False(result.IsSafeToPaste);
    }

    [Fact]
    public void DottedDate_WithDayAboveTwelve_IsSafelyDayFirst()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "personal.date_of_birth",
            "29.04.2002",
            Context(formatHint: "DD/MM/YYYY"));

        Assert.Equal(TargetValueAdaptationStatus.Adapted, result.Status);
        Assert.Equal("29/04/2002", result.Value);
        Assert.True(result.IsSafeToPaste);
    }

    [Fact]
    public void DottedDate_WithBothComponentsAtMostTwelve_RemainsAmbiguous()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "personal.date_of_birth",
            "04.05.2002",
            Context(formatHint: "DD/MM/YYYY"));

        Assert.Equal(TargetValueAdaptationStatus.Ambiguous, result.Status);
        Assert.Equal("04.05.2002", result.Value);
        Assert.False(result.IsSafeToPaste);
    }

    [Fact]
    public void DateHint_DoesNotTransformNonDateCanonicalField()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "passport.number",
            "2025-07-04",
            Context(formatHint: "DD/MM/YYYY"));

        Assert.Equal(TargetValueAdaptationStatus.Unchanged, result.Status);
        Assert.Equal("2025-07-04", result.Value);
    }

    [Fact]
    public void DigitsOnlyPhone_PreservesLeadingZeroes()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "contact.mobile",
            "0987 654-3210",
            Context(formatHint: "Digits only"));

        Assert.Equal(TargetValueAdaptationStatus.Adapted, result.Status);
        Assert.Equal(
            TargetValueAdaptationKind.PhoneDigitsOnly,
            result.Adaptation);
        Assert.Equal("09876543210", result.Value);
    }

    [Fact]
    public void DigitsOnlyPhone_RejectsValueWithoutDigits()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "contact.mobile",
            "not available",
            Context(formatHint: "Numbers only"));

        Assert.Equal(TargetValueAdaptationStatus.Invalid, result.Status);
        Assert.Equal("not available", result.Value);
        Assert.False(result.IsSafeToPaste);
    }

    [Fact]
    public void CompactInternationalPhone_PreservesPlusPrefix()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "contact.mobile",
            "+91 (987) 654-3210",
            Context(formatHint: "Compact international; no spaces"));

        Assert.Equal(TargetValueAdaptationStatus.Adapted, result.Status);
        Assert.Equal(
            TargetValueAdaptationKind.PhoneCompactInternational,
            result.Adaptation);
        Assert.Equal("+919876543210", result.Value);
    }

    [Fact]
    public void E164_ConvertsExplicitInternationalDialPrefix()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "contact.mobile",
            "00 44 20 7946 0958",
            Context(formatHint: "E.164"));

        Assert.Equal(TargetValueAdaptationStatus.Adapted, result.Status);
        Assert.Equal("+442079460958", result.Value);
    }

    [Fact]
    public void InternationalFormattingWithoutKnownPrefix_IsAmbiguous()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "contact.mobile",
            "0987 654 3210",
            Context(formatHint: "Compact international"));

        Assert.Equal(TargetValueAdaptationStatus.Ambiguous, result.Status);
        Assert.Equal("0987 654 3210", result.Value);
        Assert.False(result.IsSafeToPaste);
    }

    [Theory]
    [InlineData("National number only")]
    [InlineData("Without country code")]
    [InlineData("Last 10 digits")]
    public void DestructivePhoneInstructions_AreNotApplied(string formatHint)
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "contact.mobile",
            "+919876543210",
            Context(formatHint: formatHint));

        Assert.Equal(TargetValueAdaptationStatus.Ambiguous, result.Status);
        Assert.Equal("+919876543210", result.Value);
        Assert.False(result.IsSafeToPaste);
    }

    [Fact]
    public void TelephoneInputTypeAlone_DoesNotChangePhone()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "contact.mobile",
            "+91 98765 43210",
            Context(inputType: "tel"));

        Assert.Equal(TargetValueAdaptationStatus.Unchanged, result.Status);
        Assert.Equal("+91 98765 43210", result.Value);
    }

    [Fact]
    public void ConflictingPhoneRequirements_AreNotApplied()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "contact.mobile",
            "+91 98765 43210",
            Context(formatHint: "E.164 digits only"));

        Assert.Equal(TargetValueAdaptationStatus.Ambiguous, result.Status);
        Assert.Equal("+91 98765 43210", result.Value);
    }

    [Theory]
    [InlineData("Do not use E.164")]
    [InlineData("Digits only are prohibited")]
    public void NegatedPhoneFormat_IsNotApplied(string formatHint)
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "contact.mobile",
            "+91 98765 43210",
            Context(formatHint: formatHint));

        Assert.Equal(TargetValueAdaptationStatus.Ambiguous, result.Status);
        Assert.Equal("+91 98765 43210", result.Value);
        Assert.False(result.IsSafeToPaste);
    }

    [Fact]
    public void PhoneExtension_IsNeverFoldedIntoSubscriberNumber()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "contact.landline",
            "+44 20 7946 0958 ext 42",
            Context(formatHint: "E.164"));

        Assert.Equal(TargetValueAdaptationStatus.Ambiguous, result.Status);
        Assert.Equal("+44 20 7946 0958 ext 42", result.Value);
        Assert.False(result.IsSafeToPaste);
    }

    [Theory]
    [InlineData("+44 20 7946 0958 #42")]
    [InlineData("+44 20 7946 0958;ext=42")]
    [InlineData("+44 20 7946 0958,42")]
    [InlineData("+44 20 7946 0958;42")]
    public void NumericExtensionOrPauseSyntax_IsNeverFoldedIntoSubscriberNumber(
        string value)
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "contact.landline",
            value,
            Context(formatHint: "E.164"));

        Assert.Equal(TargetValueAdaptationStatus.Ambiguous, result.Status);
        Assert.Equal(value, result.Value);
        Assert.False(result.IsSafeToPaste);
    }

    [Fact]
    public void UnknownCanonicalField_IsInvalid()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "unknown.field",
            "value",
            Context(formatHint: "UPPERCASE"));

        Assert.Equal(TargetValueAdaptationStatus.Invalid, result.Status);
        Assert.False(result.IsSafeToPaste);
    }

    [Fact]
    public void StableCustomField_DefaultsToUnchangedText()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "custom.internal_reference.a1b2c3d4",
            "Ref-123",
            Context());

        Assert.Equal(TargetValueAdaptationStatus.Unchanged, result.Status);
        Assert.Equal("Ref-123", result.Value);
        Assert.True(result.IsSafeToPaste);
    }

    [Fact]
    public void ExplicitCaseRequirement_CanSafelyApplyToCustomText()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "custom.internal_reference.a1b2c3d4",
            "Ref-123",
            Context(formatHint: "UPPERCASE"));

        Assert.Equal(TargetValueAdaptationStatus.Adapted, result.Status);
        Assert.Equal("REF-123", result.Value);
    }

    [Fact]
    public void DatePatternInAccessibleName_IsAnExplicitTargetFormat()
    {
        TargetValueAdaptationResult result = _adapter.Adapt(
            "personal.date_of_birth",
            "29.04.2002",
            Context(accessibleName: "Date of birth (DD/MM/YYYY)"));

        Assert.Equal(TargetValueAdaptationStatus.Adapted, result.Status);
        Assert.Equal("29/04/2002", result.Value);
    }

    private static FocusedFieldContext Context(
        string accessibleName = "",
        string helpText = "",
        string placeholder = "",
        string inputType = "",
        string formatHint = "") =>
        new(
            "chrome.exe",
            "Edit",
            AccessibleName: accessibleName,
            AutomationId: "",
            HelpText: helpText,
            ClassName: "Chrome_RenderWidgetHostHWND",
            IsPassword: false,
            IsReadOnly: false,
            IsEnabled: true,
            SavedCanonicalFieldId: null,
            Placeholder: placeholder,
            SectionHeading: "",
            InputType: inputType,
            FormatHint: formatHint);
}
