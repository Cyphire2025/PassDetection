using SmartCopyPaste.Core.Catalog;
using SmartCopyPaste.Core.Normalization;

namespace SmartCopyPaste.Core.Tests;

public sealed class NormalizationAndCatalogTests
{
    [Theory]
    [InlineData("  Last_Name  ", "last name")]
    [InlineData("PassportNumber", "passport number")]
    [InlineData("PPTNo", "ppt no")]
    [InlineData("passport---number", "passport number")]
    [InlineData("Passport #", "passport number")]
    [InlineData("Ｐａｓｓｐｏｒｔ　Ｎｕｍｂｅｒ", "passport number")]
    [InlineData("Date.of   Birth", "date of birth")]
    public void Normalizer_ProducesStableExactKeys(string input, string expected)
    {
        Assert.Equal(expected, DeterministicTextNormalizer.Normalize(input));
    }

    [Fact]
    public void DefaultCatalog_CoversEveryRequiredPromptGroupWithStableIds()
    {
        CanonicalFieldCatalog catalog = CanonicalFieldCatalog.Default;

        Assert.Equal(CanonicalFieldCatalog.CurrentVersion, catalog.Version);
        Assert.True(catalog.Definitions.Count >= 55);
        Assert.Equal(
            catalog.Definitions.Count,
            catalog.Definitions.Select(definition => definition.Id).Distinct().Count());
        Assert.Contains(catalog.Definitions, definition => definition.Id == "personal.surname");
        Assert.Contains(catalog.Definitions, definition => definition.Id == "passport.number");
        Assert.Contains(catalog.Definitions, definition => definition.Id == "contact.email");
        Assert.Contains(catalog.Definitions, definition => definition.Id == "address.postal_code");
        Assert.Contains(catalog.Definitions, definition => definition.Id == "travel.arrival_date");
        Assert.Contains(catalog.Definitions, definition => definition.Id == "emergency.phone");
        Assert.All(
            catalog.Definitions,
            definition =>
            {
                Assert.NotEmpty(definition.SourceAliases);
                Assert.NotEmpty(definition.TargetAliases);
            });
    }

    [Theory]
    [InlineData("Surname", "personal.surname")]
    [InlineData("FamilyName", "personal.surname")]
    [InlineData("Surname as per Passport", "personal.surname")]
    [InlineData("Passport No.", "passport.number")]
    [InlineData("Passport #", "passport.number")]
    [InlineData("Document Number", "passport.number")]
    [InlineData("DOB", "personal.date_of_birth")]
    [InlineData("PIN Code", "address.postal_code")]
    public void ResolveHeader_UsesBroadExactSourceAliases(
        string header,
        string expectedId)
    {
        AliasMatch match = CanonicalFieldCatalog.Default.ResolveHeader(header);

        Assert.Equal(AliasMatchStatus.Unique, match.Status);
        Assert.Equal(expectedId, match.CanonicalFieldId);
    }

    [Theory]
    [InlineData("Document Number")]
    [InlineData("Issue Date")]
    [InlineData("Date of Issue")]
    [InlineData("Expiry Date")]
    [InlineData("Valid Until")]
    [InlineData("Issuing Authority")]
    [InlineData("Application Number")]
    [InlineData("Visa Number")]
    [InlineData("Booking Ref")]
    public void ResolveTarget_DoesNotAutoMatchUnsafeGenericIdentifiers(string target)
    {
        AliasMatch match = CanonicalFieldCatalog.Default.ResolveTarget(target);

        Assert.Equal(AliasMatchStatus.Unknown, match.Status);
        Assert.Null(match.CanonicalFieldId);
    }

    [Fact]
    public void SourceAndTargetAliases_AreSeparate()
    {
        CanonicalFieldCatalog catalog = CanonicalFieldCatalog.Default;

        Assert.Equal(
            "passport.issue_date",
            catalog.ResolveHeader("Issue Date").CanonicalFieldId);
        Assert.Equal(
            AliasMatchStatus.Unknown,
            catalog.ResolveTarget("Issue Date").Status);
    }

    [Fact]
    public void DefaultCatalog_AllConfiguredAliasesResolveBackToTheirOwnField()
    {
        CanonicalFieldCatalog catalog = CanonicalFieldCatalog.Default;

        foreach (CanonicalFieldDefinition definition in catalog.Definitions)
        {
            foreach (string alias in definition.SourceAliases)
            {
                AliasMatch match = catalog.ResolveHeader(alias);
                Assert.Equal(AliasMatchStatus.Unique, match.Status);
                Assert.Equal(definition.Id, match.CanonicalFieldId);
            }

            foreach (string alias in definition.TargetAliases)
            {
                AliasMatch match = catalog.ResolveTarget(alias);
                Assert.Equal(AliasMatchStatus.Unique, match.Status);
                Assert.Equal(definition.Id, match.CanonicalFieldId);
            }
        }
    }

    [Fact]
    public void ResolveAlias_ReportsAmbiguityInsteadOfChoosingByOrder()
    {
        var first = new CanonicalFieldDefinition(
            "test.first",
            "First",
            "Test",
            CanonicalFieldValueKind.Text,
            CanonicalFieldSensitivity.Personal,
            new[] { "Shared" },
            new[] { "Shared" },
            Array.Empty<string>());
        var second = first with
        {
            Id = "test.second",
            DisplayName = "Second",
        };
        var catalog = new CanonicalFieldCatalog(1, new[] { second, first });

        AliasMatch headerMatch = catalog.ResolveHeader("shared");
        AliasMatch targetMatch = catalog.ResolveTarget("SHARED");

        Assert.Equal(AliasMatchStatus.Ambiguous, headerMatch.Status);
        Assert.Equal(new[] { "test.first", "test.second" }, headerMatch.CandidateFieldIds);
        Assert.Equal(AliasMatchStatus.Ambiguous, targetMatch.Status);
        Assert.Null(targetMatch.CanonicalFieldId);
    }
}
