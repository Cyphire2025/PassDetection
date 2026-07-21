using System.Globalization;
using SmartCopyPaste.Core.Catalog;
using SmartCopyPaste.Core.Normalization;

namespace SmartCopyPaste.Core.Matching;

/// <summary>
/// Applies only explicit, reversible target-format requirements. It never
/// infers a transformation from visual capitalization or an ambiguous value.
/// </summary>
public sealed class TargetValueAdapter
{
    private readonly CanonicalFieldCatalog _catalog;

    public TargetValueAdapter(CanonicalFieldCatalog? catalog = null)
    {
        _catalog = catalog ?? CanonicalFieldCatalog.Default;
    }

    public TargetValueAdaptationResult Adapt(
        string canonicalFieldId,
        string value,
        FocusedFieldContext context)
    {
        ArgumentNullException.ThrowIfNull(value);
        ArgumentNullException.ThrowIfNull(context);
        if (string.IsNullOrWhiteSpace(canonicalFieldId)
            || canonicalFieldId.Length > 96)
        {
            return Invalid(value, "UNKNOWN_CANONICAL_FIELD");
        }

        if (value.Length > 32_768)
        {
            return Invalid(value, "VALUE_TOO_LARGE");
        }

        if (DeterministicTextNormalizer.Normalize(context.InputType) == "date")
        {
            return Ambiguous(value, "NATIVE_DATE_CONTROL_UNSUPPORTED");
        }

        if (!_catalog.TryGetDefinition(
            canonicalFieldId,
            out CanonicalFieldDefinition? definition)
            || definition is null)
        {
            return IsValidCustomFieldId(canonicalFieldId)
                ? AdaptCase(value, context)
                : Invalid(value, "UNKNOWN_CANONICAL_FIELD");
        }

        return definition.ValueKind switch
        {
            CanonicalFieldValueKind.Date =>
                AdaptDate(value, context),
            CanonicalFieldValueKind.Phone =>
                AdaptPhone(value, context),
            _ => AdaptCase(value, context),
        };
    }

    private static TargetValueAdaptationResult AdaptCase(
        string value,
        FocusedFieldContext context)
    {
        string metadata = ExplicitFormatMetadata(context);
        bool uppercase = ContainsAnyPhrase(
            metadata,
            "all caps",
            "capital letter",
            "capital letters",
            "upper case",
            "uppercase");
        bool lowercase = ContainsAnyPhrase(
            metadata,
            "lower case",
            "lowercase");

        if ((uppercase || lowercase) &&
            HasNegatedInstruction(
                metadata,
                "all caps",
                "capital letter",
                "capital letters",
                "lower case",
                "lowercase",
                "upper case",
                "uppercase"))
        {
            return Ambiguous(value, "NEGATED_CASE_REQUIREMENT");
        }

        if (uppercase && lowercase)
        {
            return Ambiguous(value, "CONFLICTING_CASE_REQUIREMENTS");
        }

        if (!uppercase && !lowercase)
        {
            return Unchanged(value, "NO_EXPLICIT_FORMAT_HINT");
        }

        string adapted = uppercase
            ? value.ToUpperInvariant()
            : value.ToLowerInvariant();
        if (adapted == value)
        {
            return Unchanged(value, "VALUE_ALREADY_MATCHES_CASE");
        }

        return new TargetValueAdaptationResult(
            TargetValueAdaptationStatus.Adapted,
            adapted,
            uppercase
                ? TargetValueAdaptationKind.Uppercase
                : TargetValueAdaptationKind.Lowercase,
            uppercase
                ? "EXPLICIT_UPPERCASE_REQUIREMENT"
                : "EXPLICIT_LOWERCASE_REQUIREMENT");
    }

    private static TargetValueAdaptationResult AdaptDate(
        string value,
        FocusedFieldContext context)
    {
        string formatMetadata = ExplicitFormatMetadata(context);
        if (HasNegatedInstruction(
            formatMetadata,
            "dd mm yyyy",
            "dd mmm yyyy",
            "mm dd yyyy",
            "yyyy mm dd"))
        {
            return Ambiguous(value, "NEGATED_DATE_FORMAT_REQUIREMENT");
        }

        HashSet<DateTargetFormat> targetFormats =
            DetectDateTargetFormats(context);
        if (targetFormats.Count == 0)
        {
            return Unchanged(value, "NO_EXPLICIT_DATE_FORMAT");
        }

        if (targetFormats.Count > 1)
        {
            return Ambiguous(value, "CONFLICTING_DATE_FORMAT_REQUIREMENTS");
        }

        SourceDateParseStatus parseStatus = TryParseUnambiguousSourceDate(
            value,
            out DateOnly date);
        if (parseStatus != SourceDateParseStatus.Success)
        {
            return parseStatus == SourceDateParseStatus.Ambiguous
                ? Ambiguous(value, "SOURCE_DATE_FORMAT_AMBIGUOUS")
                : Invalid(value, "SOURCE_DATE_INVALID");
        }

        DateTargetFormat target = targetFormats.Single();
        string adapted = target switch
        {
            DateTargetFormat.DayMonthYearSlash =>
                date.ToString("dd/MM/yyyy", CultureInfo.InvariantCulture),
            DateTargetFormat.DayMonthYearDash =>
                date.ToString("dd-MM-yyyy", CultureInfo.InvariantCulture),
            DateTargetFormat.YearMonthDayDash =>
                date.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture),
            DateTargetFormat.MonthDayYearSlash =>
                date.ToString("MM/dd/yyyy", CultureInfo.InvariantCulture),
            DateTargetFormat.DayShortMonthYear =>
                date.ToString("dd MMM yyyy", CultureInfo.InvariantCulture),
            _ => value,
        };
        if (adapted == value)
        {
            return Unchanged(value, "VALUE_ALREADY_MATCHES_DATE_FORMAT");
        }

        return new TargetValueAdaptationResult(
            TargetValueAdaptationStatus.Adapted,
            adapted,
            TargetValueAdaptationKind.DateFormat,
            "EXPLICIT_DATE_FORMAT_REQUIREMENT");
    }

    private static SourceDateParseStatus TryParseUnambiguousSourceDate(
        string value,
        out DateOnly date)
    {
        string trimmed = value.Trim();
        if (DateOnly.TryParseExact(
            trimmed,
            "yyyy-MM-dd",
            CultureInfo.InvariantCulture,
            DateTimeStyles.None,
            out date))
        {
            return SourceDateParseStatus.Success;
        }

        string[] textualMonthFormats =
        [
            "d MMM yyyy",
            "dd MMM yyyy",
            "d MMMM yyyy",
            "dd MMMM yyyy",
        ];
        if (DateOnly.TryParseExact(
            trimmed,
            textualMonthFormats,
            CultureInfo.InvariantCulture,
            DateTimeStyles.AllowWhiteSpaces,
            out date))
        {
            return SourceDateParseStatus.Success;
        }

        char separator;
        if (trimmed.Contains('.'))
        {
            separator = '.';
        }
        else if (trimmed.Contains('/'))
        {
            separator = '/';
        }
        else if (trimmed.Contains('-'))
        {
            separator = '-';
        }
        else
        {
            date = default;
            return SourceDateParseStatus.Invalid;
        }

        string[] parts = trimmed.Split(
            separator,
            StringSplitOptions.TrimEntries);
        if (parts.Length != 3
            || parts.Any(part => part.Length == 0)
            || !parts.All(part => part.All(character =>
                character is >= '0' and <= '9')))
        {
            date = default;
            return SourceDateParseStatus.Invalid;
        }

        if (parts[0].Length == 4
            && TryCreateDate(parts[0], parts[1], parts[2], out date))
        {
            return SourceDateParseStatus.Success;
        }

        if (parts[2].Length != 4
            || !int.TryParse(
                parts[0],
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out int first)
            || !int.TryParse(
                parts[1],
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out int second))
        {
            date = default;
            return SourceDateParseStatus.Invalid;
        }

        if (first is >= 1 and <= 12 && second is >= 1 and <= 12)
        {
            date = default;
            return SourceDateParseStatus.Ambiguous;
        }

        if (first > 12
            && second is >= 1 and <= 12
            && TryCreateDate(parts[2], parts[1], parts[0], out date))
        {
            return SourceDateParseStatus.Success;
        }

        if (second > 12
            && first is >= 1 and <= 12
            && TryCreateDate(parts[2], parts[0], parts[1], out date))
        {
            return SourceDateParseStatus.Success;
        }

        date = default;
        return SourceDateParseStatus.Invalid;
    }

    private static bool TryCreateDate(
        string year,
        string month,
        string day,
        out DateOnly date)
    {
        string isoCandidate =
            $"{year.PadLeft(4, '0')}-{month.PadLeft(2, '0')}-{day.PadLeft(2, '0')}";
        return DateOnly.TryParseExact(
            isoCandidate,
            "yyyy-MM-dd",
            CultureInfo.InvariantCulture,
            DateTimeStyles.None,
            out date);
    }

    private static TargetValueAdaptationResult AdaptPhone(
        string value,
        FocusedFieldContext context)
    {
        string metadata = ExplicitFormatMetadata(context);
        if (ContainsAnyPhrase(
            metadata,
            "exclude country code",
            "last 10 digits",
            "local number",
            "national number",
            "remove country code",
            "without country code"))
        {
            return Ambiguous(value, "DESTRUCTIVE_PHONE_FORMAT_REQUIREMENT");
        }

        bool digitsOnly = ContainsAnyPhrase(
            metadata,
            "digits only",
            "numbers only",
            "numeric only");
        bool e164 = ContainsPhrase(metadata, "e 164");
        bool compactInternational = e164 || ContainsAnyPhrase(
            metadata,
            "compact international",
            "international compact",
            "no spaces",
            "without spaces");
        if ((digitsOnly || compactInternational) &&
            HasNegatedInstruction(
                metadata,
                "compact international",
                "digits only",
                "e 164",
                "international compact",
                "no spaces",
                "numbers only",
                "numeric only",
                "without spaces"))
        {
            return Ambiguous(value, "NEGATED_PHONE_FORMAT_REQUIREMENT");
        }

        if (digitsOnly && compactInternational)
        {
            return Ambiguous(value, "CONFLICTING_PHONE_FORMAT_REQUIREMENTS");
        }

        if ((digitsOnly || compactInternational)
            && Digits(value).Length == 0
            && value.Length > 0)
        {
            return Invalid(value, "PHONE_VALUE_HAS_NO_DIGITS");
        }

        if ((digitsOnly || compactInternational)
            && (value.Any(char.IsLetter) ||
                HasPhoneExtensionOrPauseSyntax(value)))
        {
            return Ambiguous(value, "PHONE_EXTENSION_OR_TEXT_PRESENT");
        }

        if (digitsOnly)
        {
            string digitOnlyValue = Digits(value);
            if (digitOnlyValue == value)
            {
                return Unchanged(value, "VALUE_ALREADY_DIGITS_ONLY");
            }

            return new TargetValueAdaptationResult(
                TargetValueAdaptationStatus.Adapted,
                digitOnlyValue,
                TargetValueAdaptationKind.PhoneDigitsOnly,
                "EXPLICIT_DIGITS_ONLY_REQUIREMENT");
        }

        if (!compactInternational)
        {
            return Unchanged(value, "NO_EXPLICIT_PHONE_FORMAT");
        }

        string trimmed = value.Trim();
        bool plusPrefix = trimmed.StartsWith('+');
        bool internationalDialPrefix = trimmed.StartsWith(
            "00",
            StringComparison.Ordinal);
        if (!plusPrefix && !internationalDialPrefix)
        {
            return Ambiguous(value, "INTERNATIONAL_PHONE_PREFIX_UNKNOWN");
        }

        string digits = Digits(trimmed);
        if (digits.Length == 0)
        {
            return Invalid(value, "PHONE_VALUE_HAS_NO_DIGITS");
        }

        string adapted;
        if (plusPrefix || e164)
        {
            string subscriberDigits =
                internationalDialPrefix && digits.StartsWith(
                    "00",
                    StringComparison.Ordinal)
                    ? digits[2..]
                    : digits;
            adapted = $"+{subscriberDigits}";
        }
        else
        {
            adapted = digits;
        }

        if (adapted == value)
        {
            return Unchanged(value, "VALUE_ALREADY_COMPACT_INTERNATIONAL");
        }

        return new TargetValueAdaptationResult(
            TargetValueAdaptationStatus.Adapted,
            adapted,
            TargetValueAdaptationKind.PhoneCompactInternational,
            "EXPLICIT_COMPACT_INTERNATIONAL_REQUIREMENT");
    }

    private static HashSet<DateTargetFormat> DetectDateTargetFormats(
        FocusedFieldContext context)
    {
        string raw = string.Join(
            ' ',
            context.FormatHint,
            context.AccessibleName,
            context.Placeholder,
            context.HelpText);
        string compact = string.Concat(
            raw.Where(character => !char.IsWhiteSpace(character)))
            .ToLowerInvariant();
        string normalized = DeterministicTextNormalizer.Normalize(raw);
        var formats = new HashSet<DateTargetFormat>();

        if (compact.Contains("dd/mm/yyyy", StringComparison.Ordinal))
        {
            formats.Add(DateTargetFormat.DayMonthYearSlash);
        }

        if (compact.Contains("dd-mm-yyyy", StringComparison.Ordinal))
        {
            formats.Add(DateTargetFormat.DayMonthYearDash);
        }

        if (compact.Contains("yyyy-mm-dd", StringComparison.Ordinal))
        {
            formats.Add(DateTargetFormat.YearMonthDayDash);
        }

        if (compact.Contains("mm/dd/yyyy", StringComparison.Ordinal))
        {
            formats.Add(DateTargetFormat.MonthDayYearSlash);
        }

        if (ContainsPhrase(normalized, "dd mmm yyyy"))
        {
            formats.Add(DateTargetFormat.DayShortMonthYear);
        }

        return formats;
    }

    private static string ExplicitFormatMetadata(
        FocusedFieldContext context) =>
        DeterministicTextNormalizer.Normalize(
            string.Join(
                ' ',
                context.AccessibleName,
                context.Placeholder,
                context.HelpText,
                context.FormatHint));

    private static bool ContainsAnyPhrase(
        string normalizedMetadata,
        params string[] phrases) =>
        phrases.Any(phrase => ContainsPhrase(normalizedMetadata, phrase));

    private static bool ContainsPhrase(
        string normalizedMetadata,
        string normalizedPhrase)
    {
        string paddedMetadata = $" {normalizedMetadata} ";
        return paddedMetadata.Contains(
            $" {normalizedPhrase} ",
            StringComparison.Ordinal);
    }

    private static bool HasNegatedInstruction(
        string normalizedMetadata,
        params string[] normalizedTerms)
    {
        string[] metadataTokens = normalizedMetadata.Split(
            ' ',
            StringSplitOptions.RemoveEmptyEntries |
                StringSplitOptions.TrimEntries);
        HashSet<string> negationTokens =
        [
            "avoid",
            "cannot",
            "cant",
            "disallow",
            "disallowed",
            "exclude",
            "excluding",
            "forbid",
            "forbidden",
            "never",
            "no",
            "not",
            "prohibit",
            "prohibited",
            "without",
        ];
        HashSet<string> trailingNegationTokens =
        [
            "disallowed",
            "forbidden",
            "not",
            "optional",
            "prohibited",
        ];

        foreach (string normalizedTerm in normalizedTerms)
        {
            string[] termTokens = normalizedTerm.Split(
                ' ',
                StringSplitOptions.RemoveEmptyEntries |
                    StringSplitOptions.TrimEntries);
            if (termTokens.Length == 0 ||
                termTokens.Length > metadataTokens.Length)
            {
                continue;
            }

            for (int start = 0;
                 start <= metadataTokens.Length - termTokens.Length;
                 start++)
            {
                if (!metadataTokens
                    .AsSpan(start, termTokens.Length)
                    .SequenceEqual(termTokens))
                {
                    continue;
                }

                int beforeStart = Math.Max(0, start - 4);
                if (metadataTokens[beforeStart..start].Any(
                    negationTokens.Contains))
                {
                    return true;
                }

                int afterStart = start + termTokens.Length;
                int afterEnd = Math.Min(
                    metadataTokens.Length,
                    afterStart + 3);
                if (metadataTokens[afterStart..afterEnd].Any(
                    trailingNegationTokens.Contains))
                {
                    return true;
                }
            }
        }

        return false;
    }

    private static string Digits(string value) =>
        new(value.Where(character =>
            character is >= '0' and <= '9').ToArray());

    private static bool HasPhoneExtensionOrPauseSyntax(string value) =>
        value.Contains('#', StringComparison.Ordinal) ||
        value.Contains(';', StringComparison.Ordinal) ||
        value.Contains(',', StringComparison.Ordinal);

    private static bool IsValidCustomFieldId(string canonicalFieldId) =>
        canonicalFieldId.StartsWith("custom.", StringComparison.Ordinal)
        && canonicalFieldId.Length > "custom.".Length
        && canonicalFieldId[^1] != '.'
        && canonicalFieldId.All(character =>
            character is >= 'a' and <= 'z'
                or >= '0' and <= '9'
                or '.'
                or '_');

    private static TargetValueAdaptationResult Unchanged(
        string value,
        string reasonCode) =>
        new(
            TargetValueAdaptationStatus.Unchanged,
            value,
            TargetValueAdaptationKind.None,
            reasonCode);

    private static TargetValueAdaptationResult Ambiguous(
        string value,
        string reasonCode) =>
        new(
            TargetValueAdaptationStatus.Ambiguous,
            value,
            TargetValueAdaptationKind.None,
            reasonCode);

    private static TargetValueAdaptationResult Invalid(
        string value,
        string reasonCode) =>
        new(
            TargetValueAdaptationStatus.Invalid,
            value,
            TargetValueAdaptationKind.None,
            reasonCode);

    private enum DateTargetFormat
    {
        DayMonthYearSlash,
        DayMonthYearDash,
        YearMonthDayDash,
        MonthDayYearSlash,
        DayShortMonthYear,
    }

    private enum SourceDateParseStatus
    {
        Success,
        Ambiguous,
        Invalid,
    }
}
