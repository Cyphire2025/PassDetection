using System.Globalization;
using System.Text;

namespace SmartCopyPaste.Core.Normalization;

/// <summary>
/// Produces stable comparison keys without fuzzy matching or culture-dependent behavior.
/// </summary>
public static class DeterministicTextNormalizer
{
    public const int Version = 1;

    public static string Normalize(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }

        string compatibilityNormalized = value.Normalize(NormalizationForm.FormKC);
        var result = new StringBuilder(compatibilityNormalized.Length + 8);
        bool pendingSeparator = false;

        for (int index = 0; index < compatibilityNormalized.Length; index++)
        {
            char current = compatibilityNormalized[index];
            if (current == '#')
            {
                if (result.Length > 0 && result[^1] != ' ')
                {
                    result.Append(' ');
                }

                result.Append("number");
                pendingSeparator = true;
                continue;
            }

            if (!char.IsLetterOrDigit(current))
            {
                pendingSeparator = result.Length > 0;
                continue;
            }

            char previous = index > 0 ? compatibilityNormalized[index - 1] : '\0';
            char next = index + 1 < compatibilityNormalized.Length
                ? compatibilityNormalized[index + 1]
                : '\0';

            bool camelBoundary = result.Length > 0
                && char.IsUpper(current)
                && (char.IsLower(previous)
                    || char.IsDigit(previous)
                    || (char.IsUpper(previous) && char.IsLower(next)));

            if ((pendingSeparator || camelBoundary) && result[^1] != ' ')
            {
                result.Append(' ');
            }

            result.Append(char.ToLower(current, CultureInfo.InvariantCulture));
            pendingSeparator = false;
        }

        return result.ToString().Trim();
    }

    public static IReadOnlySet<string> Tokens(string? value)
    {
        string normalized = Normalize(value);
        if (normalized.Length == 0)
        {
            return new HashSet<string>(StringComparer.Ordinal);
        }

        return normalized
            .Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .ToHashSet(StringComparer.Ordinal);
    }
}
