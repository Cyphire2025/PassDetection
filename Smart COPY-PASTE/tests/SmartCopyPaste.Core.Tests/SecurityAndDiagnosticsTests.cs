using SmartCopyPaste.Core.Diagnostics;
using SmartCopyPaste.Core.Security;

namespace SmartCopyPaste.Core.Tests;

public sealed class SecurityAndDiagnosticsTests
{
    [Theory]
    [InlineData("One-time password")]
    [InlineData("One-time PIN")]
    [InlineData("OneTimePassword")]
    [InlineData("2FA code")]
    [InlineData("2FA Code")]
    [InlineData("Two-factor authentication code")]
    [InlineData("MFA code")]
    [InlineData("Authentication code")]
    [InlineData("authenticatorCode")]
    [InlineData("TOTP")]
    public void AuthenticationFieldMetadata_IsProtected(string metadata)
    {
        Assert.True(
            ProtectedAuthenticationFieldClassifier.IsProtected(metadata));
    }

    [Theory]
    [InlineData("Country code")]
    [InlineData("Country calling code")]
    [InlineData("Include country code")]
    [InlineData("Passport number")]
    [InlineData("Mobile number")]
    public void BenignPassengerMetadata_IsNotAuthenticationProtected(
        string metadata)
    {
        Assert.False(
            ProtectedAuthenticationFieldClassifier.IsProtected(metadata));
    }

    [Fact]
    public void OversizedAuthenticationMetadata_IsProtectedWithoutParsing()
    {
        string oversized = new(
            'x',
            ProtectedAuthenticationFieldClassifier.MaximumMetadataCharacters + 1);

        Assert.True(
            ProtectedAuthenticationFieldClassifier.IsProtected(oversized));
    }

    [Theory]
    [InlineData("passport.number", "Z1234567", "Z12••••7")]
    [InlineData("contact.email", "rahul@example.com", "r••••@example.com")]
    [InlineData("contact.mobile", "9876543210", "••••••3210")]
    [InlineData("personal.surname", "Sharma", "S•••••")]
    public void Mask_UsesFieldSpecificSafePreview(
        string fieldId,
        string value,
        string expected)
    {
        Assert.Equal(expected, SensitiveDataMasker.Mask(fieldId, value));
    }

    [Fact]
    public void Mask_UnknownCustomFieldRevealsNoValueCharacters()
    {
        string masked = SensitiveDataMasker.Mask(
            "custom.internal_reference",
            "ABC-123-SECRET");

        Assert.DoesNotContain("ABC", masked, StringComparison.Ordinal);
        Assert.DoesNotContain("123", masked, StringComparison.Ordinal);
        Assert.All(masked, character => Assert.Equal('•', character));
    }

    [Fact]
    public void Redactor_RemovesAssignmentsEmailPhoneAndUserPath()
    {
        const string input =
            "passport number=Z1234567; user rahul@example.com; phone +91 98765 43210; "
            + @"file C:\Users\nipun\Documents\Passenger.xlsx";

        string redacted = DiagnosticRedactor.Redact(input);

        Assert.DoesNotContain("Z1234567", redacted, StringComparison.Ordinal);
        Assert.DoesNotContain("rahul@example.com", redacted, StringComparison.Ordinal);
        Assert.DoesNotContain("98765", redacted, StringComparison.Ordinal);
        Assert.DoesNotContain("nipun", redacted, StringComparison.OrdinalIgnoreCase);
        Assert.Contains(DiagnosticRedactor.RedactedValue, redacted, StringComparison.Ordinal);
        Assert.Contains("<path>", redacted, StringComparison.Ordinal);
    }

    [Fact]
    public void RedactMetadata_UsesKeyPolicyEvenForUnusualValues()
    {
        IReadOnlyDictionary<string, string> result =
            DiagnosticRedactor.RedactMetadata(
                new Dictionary<string, string>
                {
                    ["passport_value"] = "UNUSUAL SECRET VALUE",
                    ["result"] = "success",
                });

        Assert.Equal(
            DiagnosticRedactor.RedactedValue,
            result["passport_value"]);
        Assert.Equal("success", result["result"]);
    }

    [Fact]
    public void SanitizedDiagnosticEvent_RedactsMetadataOnConstruction()
    {
        SanitizedDiagnosticEvent item = SanitizedDiagnosticEvent.Create(
            DateTimeOffset.UnixEpoch,
            "MATCH_COMPLETED",
            "matcher",
            DiagnosticSeverity.Information,
            new Dictionary<string, string>
            {
                ["passport_number"] = "Z1234567",
                ["canonical_field"] = "passport.number",
            });

        Assert.Equal(
            DiagnosticRedactor.RedactedValue,
            item.Metadata["passport_number"]);
        Assert.Equal(
            "passport.number",
            item.Metadata["canonical_field"]);
    }

    [Fact]
    public void DiagnosticReport_BoundsEventHistoryAndContainsNoPassengerModels()
    {
        var snapshot = new SanitizedDiagnosticSnapshot(
            "1.0.0",
            1,
            1,
            HeaderTemplateCount: 2,
            ActivePassengerCount: 3,
            IsPaused: false,
            HotkeyRegistrationStatus: "ready",
            LastErrorCode: null);
        SanitizedDiagnosticEvent[] events = Enumerable.Range(0, 105)
            .Select(index => SanitizedDiagnosticEvent.Create(
                DateTimeOffset.UnixEpoch.AddSeconds(index),
                $"EVENT_{index}",
                "core",
                DiagnosticSeverity.Information))
            .ToArray();

        SanitizedDiagnosticReport report =
            SanitizedDiagnosticReport.Create(snapshot, events);

        Assert.Equal(100, report.Events.Count);
        Assert.Equal("EVENT_5", report.Events[0].Code);
        Assert.Equal("EVENT_104", report.Events[^1].Code);
    }
}
