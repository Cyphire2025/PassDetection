using System.Collections.ObjectModel;

namespace SmartCopyPaste.Core.Session;

/// <summary>
/// A temporary, in-memory passenger profile. This model is intentionally not a
/// persistence contract.
/// </summary>
public sealed class PassengerProfile
{
    public PassengerProfile(
        Guid profileId,
        IReadOnlyDictionary<string, string> fields,
        string displayName,
        int? sourceRowNumber = null,
        Guid? headerTemplateId = null,
        DateTimeOffset? createdAt = null)
    {
        if (profileId == Guid.Empty)
        {
            throw new ArgumentException("Profile identifier cannot be empty.", nameof(profileId));
        }

        ArgumentNullException.ThrowIfNull(fields);
        ArgumentException.ThrowIfNullOrWhiteSpace(displayName);
        if (displayName.Length > 160)
        {
            throw new ArgumentOutOfRangeException(
                nameof(displayName),
                "The passenger display name exceeds 160 characters.");
        }
        if (sourceRowNumber is < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(sourceRowNumber));
        }

        if (fields.Count is < 1 or > 128)
        {
            throw new ArgumentOutOfRangeException(
                nameof(fields),
                "A passenger profile must contain between 1 and 128 fields.");
        }

        var copiedFields = new Dictionary<string, string>(StringComparer.Ordinal);
        int totalCharacters = 0;
        foreach ((string fieldId, string value) in fields)
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(fieldId);
            ArgumentNullException.ThrowIfNull(value);
            if (!IsStableFieldId(fieldId)
                || value.Length > 2_048)
            {
                throw new ArgumentOutOfRangeException(
                    nameof(fields),
                    "A passenger field exceeds its size limit.");
            }

            totalCharacters += fieldId.Length + value.Length;
            if (totalCharacters > 262_144)
            {
                throw new ArgumentOutOfRangeException(
                    nameof(fields),
                    "The passenger profile exceeds its total size limit.");
            }

            copiedFields.Add(fieldId, value);
        }

        ProfileId = profileId;
        Fields = new ReadOnlyDictionary<string, string>(copiedFields);
        DisplayName = displayName;
        SourceRowNumber = sourceRowNumber;
        HeaderTemplateId = headerTemplateId;
        CreatedAt = createdAt ?? DateTimeOffset.UtcNow;
    }

    public Guid ProfileId { get; }

    public IReadOnlyDictionary<string, string> Fields { get; }

    public string DisplayName { get; }

    public int? SourceRowNumber { get; }

    public Guid? HeaderTemplateId { get; }

    public DateTimeOffset CreatedAt { get; }

    public static PassengerProfile Create(
        IReadOnlyDictionary<string, string> fields,
        int? sourceRowNumber = null,
        Guid? headerTemplateId = null,
        string? displayName = null)
    {
        ArgumentNullException.ThrowIfNull(fields);
        string resolvedName = string.IsNullOrWhiteSpace(displayName)
            ? ResolveDisplayName(fields, sourceRowNumber)
            : displayName.Trim();
        return new PassengerProfile(
            Guid.NewGuid(),
            fields,
            resolvedName,
            sourceRowNumber,
            headerTemplateId);
    }

    private static string ResolveDisplayName(
        IReadOnlyDictionary<string, string> fields,
        int? sourceRowNumber)
    {
        if (fields.TryGetValue("personal.full_name", out string? fullName)
            && !string.IsNullOrWhiteSpace(fullName))
        {
            return fullName.Trim();
        }

        fields.TryGetValue("personal.given_name", out string? givenName);
        fields.TryGetValue("personal.surname", out string? surname);
        string composed = string.Join(
            " ",
            new[] { givenName, surname }
                .Where(value => !string.IsNullOrWhiteSpace(value))
                .Select(value => value!.Trim()));
        if (composed.Length > 0)
        {
            return composed;
        }

        return sourceRowNumber is not null
            ? $"Passenger row {sourceRowNumber.Value}"
            : "Passenger";
    }

    private static bool IsStableFieldId(string fieldId)
    {
        return fieldId.Length is >= 3 and <= 96
            && fieldId[0] != '.'
            && fieldId[^1] != '.'
            && fieldId.All(character =>
                character is >= 'a' and <= 'z'
                || character is >= '0' and <= '9'
                || character is '_' or '.');
    }
}
