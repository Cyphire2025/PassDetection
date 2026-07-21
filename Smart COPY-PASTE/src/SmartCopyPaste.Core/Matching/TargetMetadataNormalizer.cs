using SmartCopyPaste.Core.Normalization;

namespace SmartCopyPaste.Core.Matching;

/// <summary>
/// Removes presentation-only label decorations while retaining semantic context.
/// The output is suitable for deterministic alias matching, not display.
/// </summary>
internal static class TargetMetadataNormalizer
{
    private static readonly HashSet<string> TrailingDecorators =
        new(StringComparer.Ordinal)
        {
            "field",
            "mandatory",
            "optional",
            "required",
        };

    private static readonly HashSet<string> LeadingDecorators =
        new(StringComparer.Ordinal)
        {
            "choose",
            "confirm",
            "enter",
            "mandatory",
            "please",
            "provide",
            "required",
            "select",
            "type",
            "your",
        };

    private static readonly HashSet<string> PossessiveSubjects =
        new(StringComparer.Ordinal)
        {
            "applicant",
            "holder",
            "passenger",
            "traveler",
            "traveller",
        };

    public static string NormalizeLabel(string? value)
    {
        string normalized = DeterministicTextNormalizer.Normalize(value);
        if (normalized.Length == 0)
        {
            return string.Empty;
        }

        List<string> tokens = normalized
            .Split(
                ' ',
                StringSplitOptions.RemoveEmptyEntries
                    | StringSplitOptions.TrimEntries)
            .ToList();

        RemoveLeadingDecorators(tokens);
        RemoveTrailingDecorators(tokens);
        RemovePossessiveArtifacts(tokens);
        RewriteSafeLabelTokens(tokens);
        RemoveTrailingDecorators(tokens);

        return string.Join(' ', tokens);
    }

    private static void RemoveLeadingDecorators(List<string> tokens)
    {
        bool removed;
        do
        {
            removed = false;
            while (tokens.Count > 0 && LeadingDecorators.Contains(tokens[0]))
            {
                tokens.RemoveAt(0);
                removed = true;
            }

            if (tokens.Count >= 2
                && tokens[0] == "re"
                && tokens[1] == "enter")
            {
                tokens.RemoveRange(0, 2);
                removed = true;
            }
        }
        while (removed);
    }

    private static void RemoveTrailingDecorators(List<string> tokens)
    {
        while (tokens.Count > 0 && TrailingDecorators.Contains(tokens[^1]))
        {
            tokens.RemoveAt(tokens.Count - 1);
        }
    }

    private static void RemovePossessiveArtifacts(List<string> tokens)
    {
        for (int index = tokens.Count - 1; index > 0; index--)
        {
            if (tokens[index] == "s"
                && PossessiveSubjects.Contains(tokens[index - 1]))
            {
                tokens.RemoveAt(index);
            }
        }
    }

    private static void RewriteSafeLabelTokens(List<string> tokens)
    {
        for (int index = 0; index + 1 < tokens.Count; index++)
        {
            if (tokens[index] == "e" && tokens[index + 1] == "mail")
            {
                tokens[index] = "email";
                tokens.RemoveAt(index + 1);
            }
        }

        bool hasIdentifierOrPhoneContext = tokens.Any(token =>
            token is "document"
                or "flight"
                or "id"
                or "landline"
                or "mobile"
                or "national"
                or "passport"
                or "phone"
                or "tel"
                or "telephone");
        if (!hasIdentifierOrPhoneContext)
        {
            return;
        }

        for (int index = 0; index < tokens.Count; index++)
        {
            if (tokens[index] == "no")
            {
                tokens[index] = "number";
            }
        }
    }
}
