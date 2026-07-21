using System.Collections.ObjectModel;
using System.Text.RegularExpressions;
using SmartCopyPaste.Core.Normalization;

namespace SmartCopyPaste.Core.Security;

public static partial class DiagnosticRedactor
{
    public const string RedactedValue = "<redacted>";
    public const int MaximumDiagnosticTextLength = 1_024;

    private static readonly string[] SensitiveKeyFragments =
    [
        "address",
        "birth",
        "email",
        "name",
        "national id",
        "passport",
        "phone",
        "mobile",
        "religion",
        "surname",
    ];

    public static string Redact(string? text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return string.Empty;
        }

        string bounded = text.Length > MaximumDiagnosticTextLength
            ? text[..MaximumDiagnosticTextLength]
            : text;
        bounded = string.Concat(
            bounded.Where(character =>
                character is '\r' or '\n' or '\t'
                || !char.IsControl(character)));
        bounded = SensitiveAssignmentRegex().Replace(
            bounded,
            match => $"{match.Groups[1].Value}={RedactedValue}");
        bounded = EmailRegex().Replace(bounded, RedactedValue);
        bounded = PhoneLikeRegex().Replace(bounded, RedactedValue);
        bounded = WindowsUserPathRegex().Replace(bounded, "<path>");
        return bounded;
    }

    public static string RedactValue(string key, string? value)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(key);
        string normalizedKey = DeterministicTextNormalizer.Normalize(key);
        if (SensitiveKeyFragments.Any(fragment =>
            normalizedKey.Contains(fragment, StringComparison.Ordinal)))
        {
            return RedactedValue;
        }

        return Redact(value);
    }

    public static IReadOnlyDictionary<string, string> RedactMetadata(
        IReadOnlyDictionary<string, string> metadata)
    {
        ArgumentNullException.ThrowIfNull(metadata);
        var sanitized = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach ((string key, string value) in metadata)
        {
            sanitized[key] = RedactValue(key, value);
        }

        return new ReadOnlyDictionary<string, string>(sanitized);
    }

    [GeneratedRegex(
        @"(?i)\b(passport(?:\s+(?:number|no))?|email(?:\s+address)?|mobile(?:\s+number)?|phone(?:\s+number)?|surname|date\s+of\s+birth|national\s+id(?:\s+number)?)\s*[:=]\s*([^,;|\r\n]+)",
        RegexOptions.CultureInvariant)]
    private static partial Regex SensitiveAssignmentRegex();

    [GeneratedRegex(
        @"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b",
        RegexOptions.CultureInvariant)]
    private static partial Regex EmailRegex();

    [GeneratedRegex(
        @"(?<!\d)(?:\+?\d[\d ()\-]{5,}\d)(?!\d)",
        RegexOptions.CultureInvariant)]
    private static partial Regex PhoneLikeRegex();

    [GeneratedRegex(
        @"(?i)\b[A-Z]:\\Users\\[^\\\r\n]+(?:\\[^,\s;\r\n]+)*",
        RegexOptions.CultureInvariant)]
    private static partial Regex WindowsUserPathRegex();
}
