using SmartCopyPaste.Core.Catalog;
using SmartCopyPaste.Core.Matching;

namespace SmartCopyPaste.Core.Tests;

public sealed class RankedFieldCandidateTests
{
    private readonly FocusedFieldMatcher _matcher = new();

    [Fact]
    public void GenericTelephone_WithOnlyImportedMobile_RanksOnlyMobile()
    {
        FocusedFieldContext context = Context(
            accessibleName: "Telephone number *");

        FieldCandidateRankingResult result = _matcher.RankCandidates(
            context,
            ["contact.mobile", "personal.surname", "passport.number"]);

        Assert.True(result.HasRelatedCandidates);
        Assert.Equal(FieldCandidateRankingStatus.Ranked, result.Status);
        RankedFieldCandidate candidate = Assert.Single(result.Candidates);
        Assert.Equal("contact.mobile", candidate.CanonicalFieldId);
        Assert.Equal("Mobile Number", candidate.DisplayName);
        Assert.Equal(FieldCandidateConfidence.Medium, candidate.Confidence);
        Assert.Equal("GENERIC_TELEPHONE_RELATED", candidate.ReasonCode);
    }

    [Fact]
    public void GenericTelephone_WithMobileAndLandline_RanksExactlyThoseTwo()
    {
        string[] allAvailable = CanonicalFieldCatalog.Default.Definitions
            .Select(definition => definition.Id)
            .Append("custom.unrelated")
            .ToArray();

        FieldCandidateRankingResult result = _matcher.RankCandidates(
            Context(accessibleName: "TELEPHONE NUMBER (REQUIRED)"),
            allAvailable);

        Assert.Equal(
            new[] { "contact.landline", "contact.mobile" },
            result.Candidates
                .Select(candidate => candidate.CanonicalFieldId)
                .Order(StringComparer.Ordinal));
        Assert.All(
            result.Candidates,
            candidate => Assert.Equal(
                "GENERIC_TELEPHONE_RELATED",
                candidate.ReasonCode));
    }

    [Fact]
    public void GenericTelephone_DoesNotSilentlyChooseTheOnlyRelatedValue()
    {
        FieldMatchResult result = _matcher.Match(
            Context(accessibleName: "Telephone number *"),
            ["contact.mobile"]);

        Assert.Equal(FieldMatchStatus.Unknown, result.Status);
        Assert.Equal("contact.mobile", result.CanonicalFieldId);
        Assert.False(result.CanPaste);
        Assert.Equal(
            "RELATED_CANDIDATE_REQUIRES_CONFIRMATION",
            result.ReasonCode);
    }

    [Fact]
    public void GenericTelephone_WithBothPhoneKinds_IsAmbiguous()
    {
        FieldMatchResult result = _matcher.Match(
            Context(accessibleName: "Telephone number"),
            ["contact.landline", "contact.mobile"]);

        Assert.Equal(FieldMatchStatus.Ambiguous, result.Status);
        Assert.Null(result.CanonicalFieldId);
        Assert.False(result.CanPaste);
    }

    [Fact]
    public void GenericTelephone_WithNoRelatedValue_UsesSearchableFallback()
    {
        FieldCandidateRankingResult result = _matcher.RankCandidates(
            Context(accessibleName: "Telephone number"),
            ["personal.surname", "contact.email"]);

        Assert.Equal(
            FieldCandidateRankingStatus.NoRelatedCandidates,
            result.Status);
        Assert.False(result.HasRelatedCandidates);
        Assert.Empty(result.Candidates);
    }

    [Theory]
    [InlineData("Mobile number", "contact.mobile")]
    [InlineData("CELL PHONE *", "contact.mobile")]
    [InlineData("Landline number", "contact.landline")]
    [InlineData("Home phone", "contact.landline")]
    [InlineData("Alternate mobile number", "contact.alternate_mobile")]
    [InlineData("Country calling code", "contact.country_calling_code")]
    [InlineData("Country code for mobile number", "contact.country_calling_code")]
    [InlineData("Mobile number country code", "contact.country_calling_code")]
    [InlineData("Dialling code for telephone number", "contact.country_calling_code")]
    [InlineData("Emergency telephone number", "emergency.phone")]
    public void SpecificPhoneLabels_RankOnlyTheirSpecificCanonicalField(
        string label,
        string expectedId)
    {
        string[] phoneFields =
        [
            "contact.mobile",
            "contact.landline",
            "contact.alternate_mobile",
            "contact.country_calling_code",
            "emergency.phone",
        ];

        FieldCandidateRankingResult result = _matcher.RankCandidates(
            Context(accessibleName: label),
            phoneFields);

        RankedFieldCandidate candidate = Assert.Single(result.Candidates);
        Assert.Equal(expectedId, candidate.CanonicalFieldId);
        Assert.Equal(FieldCandidateConfidence.High, candidate.Confidence);
    }

    [Theory]
    [InlineData("Middle and given name (First name)*", "personal.given_name")]
    [InlineData("MIDDLE AND GIVEN NAME (FIRST NAME) (required)", "personal.given_name")]
    [InlineData("Surname (Last name)", "personal.surname")]
    [InlineData("SURNAME (LAST NAME) *", "personal.surname")]
    [InlineData("Re-enter Email", "contact.email")]
    [InlineData("E-mail Address (required)", "contact.email")]
    [InlineData("Identity Card", "identity.national_id_number")]
    public void ScreenshotLabels_AutoMatchFromAccessibleNameAlone(
        string accessibleName,
        string expectedId)
    {
        FocusedFieldContext context = Context(
            accessibleName: accessibleName,
            automationId: string.Empty,
            helpText: string.Empty);

        FieldMatchResult result = _matcher.Match(
            context,
            [expectedId, "personal.middle_name", "passport.number"]);

        Assert.True(result.CanPaste);
        Assert.Equal(FieldMatchStatus.Matched, result.Status);
        Assert.Equal(expectedId, result.CanonicalFieldId);
        Assert.True(result.Score >= FocusedFieldMatcher.AutomaticPasteThreshold);
    }

    [Theory]
    [InlineData("PASSPORT NUMBER *")]
    [InlineData("Passport number (required)")]
    [InlineData("Please enter your passport number")]
    [InlineData("Passport No.")]
    public void PresentationDecorations_DoNotChangeExactPassportMeaning(
        string label)
    {
        FieldMatchResult result = _matcher.Match(
            Context(accessibleName: label),
            ["passport.number"]);

        Assert.True(result.CanPaste);
        Assert.Equal("passport.number", result.CanonicalFieldId);
        Assert.Equal(95, result.Score);
    }

    [Fact]
    public void IdentityCard_DoesNotOverrideConflictingPassportContext()
    {
        FieldMatchResult result = _matcher.Match(
            Context(
                accessibleName: "Identity Card",
                automationId: "passportNumber"),
            ["identity.national_id_number", "passport.number"]);

        Assert.Equal(FieldMatchStatus.Ambiguous, result.Status);
        Assert.False(result.CanPaste);
    }

    [Fact]
    public void ApplicationIdentityLabel_DoesNotRankNationalId()
    {
        FieldCandidateRankingResult result = _matcher.RankCandidates(
            Context(accessibleName: "Application Identity Card"),
            ["identity.national_id_number", "passport.number"]);

        Assert.Equal(FieldCandidateRankingStatus.Blocked, result.Status);
        Assert.Empty(result.Candidates);
    }

    [Fact]
    public void SectionHeading_CanProvideBoundedPassportContext()
    {
        var context = Context(
            accessibleName: "Issue Date",
            sectionHeading: "Passport Details");

        FieldCandidateRankingResult result = _matcher.RankCandidates(
            context,
            ["passport.issue_date", "passport.expiry_date", "personal.date_of_birth"]);

        RankedFieldCandidate candidate = Assert.Single(result.Candidates);
        Assert.Equal("passport.issue_date", candidate.CanonicalFieldId);
        Assert.Equal("SECTION_CONTEXT", candidate.ReasonCode);

        FieldMatchResult match = _matcher.Match(
            context,
            ["passport.issue_date", "passport.expiry_date", "personal.date_of_birth"]);
        Assert.Equal(FieldMatchStatus.Unknown, match.Status);
        Assert.False(match.CanPaste);
    }

    [Fact]
    public void VisaApplicationContext_BlocksPassportCandidateRanking()
    {
        FieldCandidateRankingResult result = _matcher.RankCandidates(
            Context(
                accessibleName: "Passport Number",
                sectionHeading: "Visa Application"),
            ["passport.number"]);

        Assert.Equal(FieldCandidateRankingStatus.Blocked, result.Status);
        Assert.False(result.HasRelatedCandidates);
    }

    [Fact]
    public void RelatedTokenRanking_DoesNotUseEditDistance()
    {
        FieldCandidateRankingResult related = _matcher.RankCandidates(
            Context(accessibleName: "Applicant birth city as shown"),
            ["personal.city_of_birth", "address.city", "personal.surname"]);
        FieldCandidateRankingResult misspelled = _matcher.RankCandidates(
            Context(accessibleName: "Surnmae"),
            ["personal.surname", "personal.given_name"]);

        Assert.Equal(
            "personal.city_of_birth",
            Assert.Single(related.Candidates).CanonicalFieldId);
        Assert.Equal(
            FieldCandidateRankingStatus.NoRelatedCandidates,
            misspelled.Status);
    }

    [Fact]
    public void CandidateRanking_IsIndependentOfAvailableFieldOrder()
    {
        string[] available =
        [
            "personal.surname",
            "contact.landline",
            "contact.mobile",
            "passport.number",
        ];
        FocusedFieldContext context = Context(
            accessibleName: "Telephone number *");

        FieldCandidateRankingResult first = _matcher.RankCandidates(
            context,
            available);
        FieldCandidateRankingResult second = _matcher.RankCandidates(
            context,
            available.Reverse());

        Assert.Equal(first.Status, second.Status);
        Assert.Equal(first.ReasonCode, second.ReasonCode);
        Assert.Equal(
            first.Candidates.Select(candidate => (
                candidate.CanonicalFieldId,
                candidate.Score,
                candidate.Confidence,
                candidate.ReasonCode)),
            second.Candidates.Select(candidate => (
                candidate.CanonicalFieldId,
                candidate.Score,
                candidate.Confidence,
                candidate.ReasonCode)));
    }

    [Fact]
    public void UnknownLabel_ReturnsNoRelatedCandidates()
    {
        FieldCandidateRankingResult result = _matcher.RankCandidates(
            Context(accessibleName: "Internal reference"),
            CanonicalFieldCatalog.Default.Definitions.Select(
                definition => definition.Id));

        Assert.Equal(
            FieldCandidateRankingStatus.NoRelatedCandidates,
            result.Status);
        Assert.Empty(result.Candidates);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(13)]
    public void CandidateLimit_IsStrictlyBounded(int maximumCandidates)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            _matcher.RankCandidates(
                Context(accessibleName: "Surname"),
                ["personal.surname"],
                maximumCandidates));
    }

    [Fact]
    public void OversizedNewMetadata_IsBlocked()
    {
        FieldCandidateRankingResult result = _matcher.RankCandidates(
            Context(
                accessibleName: "Surname",
                formatHint: new string('X', 513)),
            ["personal.surname"]);

        Assert.Equal(FieldCandidateRankingStatus.Blocked, result.Status);
        Assert.Equal("FIELD_METADATA_TOO_LARGE", result.ReasonCode);
    }

    [Theory]
    [InlineData("Alternate landline number")]
    [InlineData("Secondary home phone")]
    public void AlternateLandline_DoesNotAutoPasteAlternateMobile(string label)
    {
        FieldMatchResult match = _matcher.Match(
            Context(accessibleName: label),
            ["contact.alternate_mobile", "contact.landline"]);

        Assert.False(match.CanPaste);
        Assert.NotEqual("contact.alternate_mobile", match.CanonicalFieldId);
    }

    [Fact]
    public void GenericTelephoneInSecondarySection_RequiresConfirmation()
    {
        FocusedFieldContext context = Context(
            accessibleName: "Telephone number",
            sectionHeading: "Secondary Contact");
        FieldMatchResult match = _matcher.Match(
            context,
            ["contact.alternate_mobile", "contact.mobile"]);
        FieldCandidateRankingResult ranking = _matcher.RankCandidates(
            context,
            ["contact.alternate_mobile", "contact.mobile"]);

        Assert.False(match.CanPaste);
        RankedFieldCandidate candidate = Assert.Single(ranking.Candidates);
        Assert.Equal("contact.alternate_mobile", candidate.CanonicalFieldId);
        Assert.Equal("ALTERNATE_CONTACT_RELATED", candidate.ReasonCode);
    }

    [Fact]
    public void CallingWordWithoutCode_DoesNotBecomeCountryCallingCode()
    {
        FieldMatchResult match = _matcher.Match(
            Context(accessibleName: "Telephone number for calling"),
            ["contact.country_calling_code", "contact.mobile"]);

        Assert.False(match.CanPaste);
        Assert.NotEqual(
            "contact.country_calling_code",
            match.CanonicalFieldId);
    }

    [Fact]
    public void GenericTelephoneHelpAboutCountryCode_DoesNotBecomeCodeField()
    {
        FieldCandidateRankingResult ranking = _matcher.RankCandidates(
            Context(
                accessibleName: "Telephone number",
                helpText: "Include country code"),
            [
                "contact.mobile",
                "contact.landline",
                "contact.country_calling_code",
            ]);

        Assert.Equal(
            new[] { "contact.landline", "contact.mobile" },
            ranking.Candidates
                .Select(candidate => candidate.CanonicalFieldId)
                .Order(StringComparer.Ordinal));
    }

    [Theory]
    [InlineData("Mobile number with country code", "contact.mobile")]
    [InlineData("Enter phone number including country code", null)]
    public void FullNumberCountryCodeInstruction_IsNotTheCallingCodeField(
        string label,
        string? expectedSpecificField)
    {
        FieldCandidateRankingResult ranking = _matcher.RankCandidates(
            Context(accessibleName: label),
            [
                "contact.mobile",
                "contact.landline",
                "contact.country_calling_code",
            ]);

        Assert.DoesNotContain(
            ranking.Candidates,
            candidate =>
                candidate.CanonicalFieldId == "contact.country_calling_code");
        if (expectedSpecificField is not null)
        {
            Assert.Contains(
                ranking.Candidates,
                candidate =>
                    candidate.CanonicalFieldId == expectedSpecificField);
        }
    }

    [Theory]
    [InlineData("Country code for mobile number")]
    [InlineData("Mobile number country code")]
    [InlineData("Dialing code for telephone number")]
    public void ExplicitCallingCodeTarget_NeverUsesFullPhoneNumber(
        string label)
    {
        string[] available =
        [
            "contact.mobile",
            "contact.landline",
            "contact.country_calling_code",
        ];

        FieldMatchResult match = _matcher.Match(
            Context(accessibleName: label),
            available);
        FieldCandidateRankingResult ranking = _matcher.RankCandidates(
            Context(accessibleName: label),
            available);

        Assert.Equal(
            "contact.country_calling_code",
            match.CanonicalFieldId);
        Assert.DoesNotContain(
            ranking.Candidates,
            candidate =>
                candidate.CanonicalFieldId is
                    "contact.mobile" or "contact.landline");
        Assert.Equal(
            "contact.country_calling_code",
            Assert.Single(ranking.Candidates).CanonicalFieldId);
    }

    [Theory]
    [InlineData("Email", "contact.email", "emergency.email")]
    [InlineData("Mobile number", "contact.mobile", "emergency.phone")]
    public void EmergencySection_PreventsPrimaryContactAutoPaste(
        string label,
        string primaryField,
        string emergencyField)
    {
        FocusedFieldContext context = Context(
            accessibleName: label,
            sectionHeading: "Emergency Contact");
        FieldMatchResult match = _matcher.Match(
            context,
            [primaryField, emergencyField]);
        FieldCandidateRankingResult ranking = _matcher.RankCandidates(
            context,
            [primaryField, emergencyField]);

        Assert.False(match.CanPaste);
        Assert.Equal("SECTION_CONTEXT_CONFLICT", match.ReasonCode);
        RankedFieldCandidate candidate = Assert.Single(ranking.Candidates);
        Assert.Equal(emergencyField, candidate.CanonicalFieldId);
    }

    [Theory]
    [InlineData(
        "Passport number",
        "Previous passport information",
        "passport.number",
        "passport.old_number")]
    [InlineData(
        "Nationality",
        "Previous nationality",
        "personal.nationality",
        "personal.previous_nationality")]
    [InlineData(
        "Email",
        "Alternate Contact",
        "contact.email",
        "contact.alternate_email")]
    [InlineData(
        "Mobile number",
        "Secondary Contact",
        "contact.mobile",
        "contact.alternate_mobile")]
    public void QualifiedSection_PreventsPrimaryFieldAutoPaste(
        string label,
        string section,
        string primaryField,
        string specializedField)
    {
        FocusedFieldContext context = Context(
            accessibleName: label,
            sectionHeading: section);
        FieldMatchResult match = _matcher.Match(
            context,
            [primaryField, specializedField]);
        FieldCandidateRankingResult ranking = _matcher.RankCandidates(
            context,
            [primaryField, specializedField]);

        Assert.False(match.CanPaste);
        Assert.Equal("SECTION_CONTEXT_CONFLICT", match.ReasonCode);
        Assert.DoesNotContain(
            ranking.Candidates,
            candidate => candidate.CanonicalFieldId == primaryField);
        Assert.Contains(
            ranking.Candidates,
            candidate => candidate.CanonicalFieldId == specializedField);
    }

    [Theory]
    [InlineData("Mobile extension", "contact.mobile")]
    [InlineData("Emergency phone extension", "emergency.phone")]
    [InlineData("Mobile area code", "contact.mobile")]
    [InlineData("Emergency calling code", "emergency.phone")]
    public void PhoneSubcomponentOrConflictingCode_DoesNotAutoPasteFullNumber(
        string label,
        string forbiddenFieldId)
    {
        FieldMatchResult match = _matcher.Match(
            Context(accessibleName: label),
            [
                "contact.mobile",
                "contact.landline",
                "contact.alternate_mobile",
                "contact.country_calling_code",
                "emergency.phone",
            ]);

        Assert.False(match.CanPaste);
        Assert.False(
            string.Equals(
                forbiddenFieldId,
                match.CanonicalFieldId,
                StringComparison.Ordinal) &&
            match.Status == FieldMatchStatus.Matched);

        FieldCandidateRankingResult ranking = _matcher.RankCandidates(
            Context(accessibleName: label),
            [
                "contact.mobile",
                "contact.landline",
                "contact.alternate_mobile",
                "contact.country_calling_code",
                "emergency.phone",
            ]);
        Assert.Equal(FieldCandidateRankingStatus.Blocked, ranking.Status);
        Assert.Empty(ranking.Candidates);
    }

    [Theory]
    [InlineData("Upload passport file", "", "")]
    [InlineData("Verification code", "", "")]
    [InlineData("Passenger field", "one-time-code", "")]
    [InlineData("One-time password", "text", "")]
    [InlineData("One-time PIN", "tel", "")]
    [InlineData("2FA code", "text", "")]
    [InlineData("Two-factor authentication code", "text", "")]
    [InlineData("Authentication code", "tel", "")]
    [InlineData("Passenger field", "", "Choose file")]
    [InlineData("Date of birth", "date", "")]
    [InlineData("Passenger field", "password", "")]
    public void ProtectedMetadata_IsBlocked(
        string accessibleName,
        string inputType,
        string placeholder)
    {
        FocusedFieldContext context = Context(
            accessibleName: accessibleName) with
        {
            InputType = inputType,
            Placeholder = placeholder,
        };

        FieldMatchResult match = _matcher.Match(
            context,
            ["passport.number", "contact.mobile"]);

        Assert.Equal(FieldMatchStatus.Blocked, match.Status);
        Assert.False(match.CanPaste);
    }

    [Theory]
    [InlineData("Email", "Password recovery")]
    [InlineData("Passport Number", "Passport file information")]
    public void BenignSectionWords_DoNotBlockAStandardField(
        string accessibleName,
        string sectionHeading)
    {
        FieldMatchResult match = _matcher.Match(
            Context(
                accessibleName: accessibleName,
                sectionHeading: sectionHeading),
            ["contact.email", "passport.number"]);

        Assert.NotEqual(FieldMatchStatus.Blocked, match.Status);
    }

    [Fact]
    public void CountryCode_IsNotTreatedAsAuthenticationMetadata()
    {
        FieldMatchResult match = _matcher.Match(
            Context(accessibleName: "Country code"),
            ["contact.country_calling_code", "contact.mobile"]);

        Assert.NotEqual(FieldMatchStatus.Blocked, match.Status);
    }

    private static FocusedFieldContext Context(
        string accessibleName = "",
        string automationId = "",
        string helpText = "",
        string sectionHeading = "",
        string formatHint = "") =>
        new(
            "chrome.exe",
            "Edit",
            AccessibleName: accessibleName,
            AutomationId: automationId,
            HelpText: helpText,
            ClassName: "Chrome_RenderWidgetHostHWND",
            IsPassword: false,
            IsReadOnly: false,
            IsEnabled: true,
            SavedCanonicalFieldId: null,
            Placeholder: "",
            SectionHeading: sectionHeading,
            InputType: "",
            FormatHint: formatHint);
}
