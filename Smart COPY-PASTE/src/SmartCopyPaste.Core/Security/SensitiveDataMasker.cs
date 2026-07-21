using System.Text;

namespace SmartCopyPaste.Core.Security;

public static class SensitiveDataMasker
{
    private const char MaskCharacter = '•';

    public static string Mask(string canonicalFieldId, string value)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(canonicalFieldId);
        ArgumentNullException.ThrowIfNull(value);
        if (value.Length == 0)
        {
            return string.Empty;
        }

        if (canonicalFieldId.EndsWith("email", StringComparison.Ordinal)
            || canonicalFieldId.Contains(".email", StringComparison.Ordinal))
        {
            return MaskEmail(value);
        }

        if (canonicalFieldId.Contains("phone", StringComparison.Ordinal)
            || canonicalFieldId.Contains("mobile", StringComparison.Ordinal)
            || canonicalFieldId.Contains("landline", StringComparison.Ordinal)
            || canonicalFieldId.Contains("calling_code", StringComparison.Ordinal))
        {
            return MaskPhone(value);
        }

        if (canonicalFieldId.Contains("passport", StringComparison.Ordinal)
            || canonicalFieldId.Contains("national_id", StringComparison.Ordinal))
        {
            return MaskIdentifier(value);
        }

        if (canonicalFieldId.Contains("date_of_birth", StringComparison.Ordinal))
        {
            return MaskBirthDate(value);
        }

        if (canonicalFieldId.Contains("name", StringComparison.Ordinal)
            || canonicalFieldId is "personal.surname"
            or "personal.given_name"
            or "personal.alias")
        {
            return KeepEdges(value, 1, 0);
        }

        return new string(MaskCharacter, Math.Clamp(value.Length, 4, 16));
    }

    private static string MaskEmail(string value)
    {
        int separator = value.IndexOf('@', StringComparison.Ordinal);
        if (separator <= 0 || separator == value.Length - 1)
        {
            return KeepEdges(value, 1, 0);
        }

        string local = value[..separator];
        string domain = value[(separator + 1)..];
        return $"{local[0]}{new string(MaskCharacter, Math.Clamp(local.Length - 1, 4, 12))}@{domain}";
    }

    private static string MaskPhone(string value)
    {
        string digits = string.Concat(value.Where(char.IsDigit));
        if (digits.Length <= 4)
        {
            return new string(MaskCharacter, Math.Max(4, digits.Length));
        }

        return $"{new string(MaskCharacter, Math.Clamp(digits.Length - 4, 4, 12))}{digits[^4..]}";
    }

    private static string MaskIdentifier(string value) =>
        value.Length >= 6 ? KeepEdges(value, 3, 1) : KeepEdges(value, 1, 1);

    private static string MaskBirthDate(string value)
    {
        string digits = string.Concat(value.Where(char.IsDigit));
        return digits.Length >= 4
            ? $"{new string(MaskCharacter, Math.Clamp(digits.Length - 4, 4, 8))}{digits[^4..]}"
            : new string(MaskCharacter, Math.Max(4, value.Length));
    }

    private static string KeepEdges(
        string value,
        int leadingCharacters,
        int trailingCharacters)
    {
        if (value.Length <= leadingCharacters + trailingCharacters)
        {
            return new string(MaskCharacter, Math.Max(4, value.Length));
        }

        var result = new StringBuilder(value.Length);
        result.Append(value.AsSpan(0, leadingCharacters));
        result.Append(
            MaskCharacter,
            Math.Clamp(
                value.Length - leadingCharacters - trailingCharacters,
                4,
                16));
        if (trailingCharacters > 0)
        {
            result.Append(value.AsSpan(value.Length - trailingCharacters));
        }

        return result.ToString();
    }
}
