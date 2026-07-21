using SmartCopyPaste.Core.Normalization;

namespace SmartCopyPaste.Core.Security;

/// <summary>
/// Fail-closed, bounded recognition of direct field metadata that identifies
/// authentication secrets rather than passenger data.
/// </summary>
public static class ProtectedAuthenticationFieldClassifier
{
    public const int MaximumMetadataParts = 16;
    public const int MaximumMetadataCharacters = 4096;

    private static readonly string[] ProtectedPhrases =
    [
        "one time code",
        "one time password",
        "one time pin",
        "one time passcode",
        "verification code",
        "verification pin",
        "security code",
        "security pin",
        "authentication code",
        "auth code",
        "authenticator code",
        "two factor code",
        "two factor authentication",
        "multi factor code",
        "multi factor authentication",
        "2fa code",
        "2 fa code",
        "2 factor code",
        "mfa code",
        "login code",
        "sign in code",
        "sms code",
    ];

    private static readonly HashSet<string> ProtectedTokens =
        new(
            [
                "otp",
                "totp",
                "2fa",
                "mfa",
                "passcode",
                "authenticator",
            ],
            StringComparer.Ordinal);

    public static bool IsProtected(params string?[] metadata)
    {
        ArgumentNullException.ThrowIfNull(metadata);
        if (metadata.Length > MaximumMetadataParts)
        {
            return true;
        }

        int totalCharacters = 0;
        foreach (string? item in metadata)
        {
            if (item is null)
            {
                continue;
            }

            if (item.Length > MaximumMetadataCharacters - totalCharacters)
            {
                return true;
            }

            totalCharacters += item.Length;
        }

        string normalized = DeterministicTextNormalizer.Normalize(
            string.Join(' ', metadata));
        if (normalized.Length > MaximumMetadataCharacters)
        {
            return true;
        }

        IReadOnlySet<string> tokens =
            DeterministicTextNormalizer.Tokens(normalized);
        return tokens.Overlaps(ProtectedTokens) ||
            ProtectedPhrases.Any(phrase =>
                ContainsPhrase(normalized, phrase));
    }

    private static bool ContainsPhrase(
        string normalizedMetadata,
        string normalizedPhrase) =>
        $" {normalizedMetadata} ".Contains(
            $" {normalizedPhrase} ",
            StringComparison.Ordinal);
}
