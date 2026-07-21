using SmartCopyPaste.Core.Normalization;

namespace SmartCopyPaste.Core.Catalog;

/// <summary>
/// Versioned, deterministic passenger-field catalog. Header aliases and target-control
/// aliases are deliberately indexed separately.
/// </summary>
public sealed class CanonicalFieldCatalog
{
    public const int CurrentVersion = 2;

    private readonly Dictionary<string, CanonicalFieldDefinition> _byId;
    private readonly Dictionary<string, CanonicalFieldDefinition[]> _sourceIndex;
    private readonly Dictionary<string, CanonicalFieldDefinition[]> _targetIndex;

    public CanonicalFieldCatalog(
        int version,
        IEnumerable<CanonicalFieldDefinition> definitions)
    {
        ArgumentNullException.ThrowIfNull(definitions);
        ArgumentOutOfRangeException.ThrowIfLessThan(version, 1);

        Version = version;
        CanonicalFieldDefinition[] materialized = definitions.ToArray();
        if (materialized.Length == 0)
        {
            throw new ArgumentException("At least one canonical field is required.", nameof(definitions));
        }

        ValidateDefinitions(materialized);
        Definitions = Array.AsReadOnly(materialized);
        _byId = materialized.ToDictionary(
            definition => definition.Id,
            StringComparer.Ordinal);
        _sourceIndex = BuildIndex(materialized, definition => definition.SourceAliases);
        _targetIndex = BuildIndex(materialized, definition => definition.TargetAliases);
    }

    public static CanonicalFieldCatalog Default { get; } =
        new(CurrentVersion, CreateDefaultDefinitions());

    public int Version { get; }

    public IReadOnlyList<CanonicalFieldDefinition> Definitions { get; }

    public AliasMatch ResolveHeader(string? header) => Resolve(header, _sourceIndex);

    public AliasMatch ResolveTarget(string? targetMetadata) => Resolve(targetMetadata, _targetIndex);

    public bool TryGetDefinition(
        string canonicalFieldId,
        out CanonicalFieldDefinition? definition)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(canonicalFieldId);
        return _byId.TryGetValue(canonicalFieldId, out definition);
    }

    public CanonicalFieldDefinition GetRequired(string canonicalFieldId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(canonicalFieldId);
        return _byId.TryGetValue(canonicalFieldId, out CanonicalFieldDefinition? definition)
            ? definition
            : throw new KeyNotFoundException(
                $"Unknown canonical field identifier '{canonicalFieldId}'.");
    }

    private static AliasMatch Resolve(
        string? input,
        Dictionary<string, CanonicalFieldDefinition[]> index)
    {
        string normalized = DeterministicTextNormalizer.Normalize(input);
        if (normalized.Length == 0
            || !index.TryGetValue(
                normalized,
                out CanonicalFieldDefinition[]? candidates))
        {
            return new AliasMatch(
                AliasMatchStatus.Unknown,
                normalized,
                null,
                Array.Empty<string>());
        }

        string[] candidateIds = candidates
            .Select(candidate => candidate.Id)
            .Order(StringComparer.Ordinal)
            .ToArray();
        if (candidateIds.Length != 1)
        {
            return new AliasMatch(
                AliasMatchStatus.Ambiguous,
                normalized,
                null,
                candidateIds);
        }

        return new AliasMatch(
            AliasMatchStatus.Unique,
            normalized,
            candidateIds[0],
            candidateIds);
    }

    private static Dictionary<string, CanonicalFieldDefinition[]> BuildIndex(
        IEnumerable<CanonicalFieldDefinition> definitions,
        Func<CanonicalFieldDefinition, IReadOnlyList<string>> aliasSelector)
    {
        var mutable = new Dictionary<string, List<CanonicalFieldDefinition>>(StringComparer.Ordinal);
        foreach (CanonicalFieldDefinition definition in definitions)
        {
            foreach (string alias in aliasSelector(definition))
            {
                string normalized = DeterministicTextNormalizer.Normalize(alias);
                if (normalized.Length == 0)
                {
                    continue;
                }

                if (!mutable.TryGetValue(
                    normalized,
                    out List<CanonicalFieldDefinition>? candidates))
                {
                    candidates = [];
                    mutable.Add(normalized, candidates);
                }

                if (!candidates.Any(candidate => candidate.Id == definition.Id))
                {
                    candidates.Add(definition);
                }
            }
        }

        return mutable.ToDictionary(
            pair => pair.Key,
            pair => pair.Value.OrderBy(item => item.Id, StringComparer.Ordinal).ToArray(),
            StringComparer.Ordinal);
    }

    private static void ValidateDefinitions(
        IReadOnlyList<CanonicalFieldDefinition> definitions)
    {
        var identifiers = new HashSet<string>(StringComparer.Ordinal);
        foreach (CanonicalFieldDefinition definition in definitions)
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(definition.Id);
            ArgumentException.ThrowIfNullOrWhiteSpace(definition.DisplayName);
            ArgumentException.ThrowIfNullOrWhiteSpace(definition.FieldGroup);
            ArgumentNullException.ThrowIfNull(definition.SourceAliases);
            ArgumentNullException.ThrowIfNull(definition.TargetAliases);
            ArgumentNullException.ThrowIfNull(definition.BlockingTargetTokens);

            if (!identifiers.Add(definition.Id))
            {
                throw new ArgumentException(
                    $"Duplicate canonical field identifier '{definition.Id}'.",
                    nameof(definitions));
            }

            if (!IsStableIdentifier(definition.Id))
            {
                throw new ArgumentException(
                    $"Canonical field identifier '{definition.Id}' is invalid.",
                    nameof(definitions));
            }

            if (definition.SourceAliases.Count == 0 || definition.TargetAliases.Count == 0)
            {
                throw new ArgumentException(
                    $"Canonical field '{definition.Id}' must define source and target aliases.",
                    nameof(definitions));
            }
        }
    }

    private static bool IsStableIdentifier(string value)
    {
        if (value.Length is < 3 or > 96 || value[0] == '.' || value[^1] == '.')
        {
            return false;
        }

        return value.All(character =>
            character is >= 'a' and <= 'z'
            || character is >= '0' and <= '9'
            || character is '_' or '.');
    }

    private static IReadOnlyList<CanonicalFieldDefinition> CreateDefaultDefinitions()
    {
        return
        [
            D("personal.title", "Title", "Personal", CanonicalFieldValueKind.Text,
                CanonicalFieldSensitivity.Personal, ["title", "salutation"],
                ["title", "salutation", "honorific"]),
            D("personal.surname", "Surname", "Personal", CanonicalFieldValueKind.Name,
                CanonicalFieldSensitivity.Sensitive,
                ["surname", "last name", "family name", "familyname", "last_name",
                 "applicant surname", "passenger surname", "surname as per passport"],
                ["surname", "last name", "family name", "applicant surname",
                 "surname last name"]),
            D("personal.given_name", "Given Name", "Personal", CanonicalFieldValueKind.Name,
                CanonicalFieldSensitivity.Sensitive,
                ["given name", "given names", "first name", "forename",
                 "applicant given name", "passenger given name"],
                ["given name", "given names", "first name", "forename",
                 "middle and given name first name",
                 "middle and given names first name"]),
            D("personal.middle_name", "Middle Name", "Personal", CanonicalFieldValueKind.Name,
                CanonicalFieldSensitivity.Sensitive, ["middle name", "second name"],
                ["middle name", "second name"]),
            D("personal.full_name", "Full Name", "Personal", CanonicalFieldValueKind.Name,
                CanonicalFieldSensitivity.Sensitive,
                ["full name", "passenger name", "applicant name", "traveller name", "traveler name"],
                ["full name", "passenger name", "applicant name"]),
            D("personal.previous_name", "Previous Name", "Personal", CanonicalFieldValueKind.Name,
                CanonicalFieldSensitivity.Sensitive,
                ["previous name", "former name", "maiden name"],
                ["previous name", "former name", "maiden name"]),
            D("personal.alias", "Alias", "Personal", CanonicalFieldValueKind.Name,
                CanonicalFieldSensitivity.Sensitive,
                ["alias", "other name", "also known as"],
                ["alias", "other name", "also known as"]),
            D("personal.gender", "Gender", "Personal", CanonicalFieldValueKind.Gender,
                CanonicalFieldSensitivity.Sensitive, ["gender", "sex"],
                ["gender", "sex"]),
            D("personal.marital_status", "Marital Status", "Personal",
                CanonicalFieldValueKind.Text, CanonicalFieldSensitivity.Sensitive,
                ["marital status", "civil status"], ["marital status", "civil status"]),
            D("personal.date_of_birth", "Date of Birth", "Personal",
                CanonicalFieldValueKind.Date, CanonicalFieldSensitivity.HighlySensitive,
                ["date of birth", "dob", "birth date", "birthdate"],
                ["date of birth", "dob", "birth date", "birthdate"]),
            D("personal.place_of_birth", "Place of Birth", "Personal",
                CanonicalFieldValueKind.Text, CanonicalFieldSensitivity.Sensitive,
                ["place of birth", "birth place", "birthplace"],
                ["place of birth", "birth place", "birthplace"]),
            D("personal.city_of_birth", "City of Birth", "Personal",
                CanonicalFieldValueKind.Text, CanonicalFieldSensitivity.Sensitive,
                ["city of birth", "birth city"], ["city of birth", "birth city"]),
            D("personal.country_of_birth", "Country of Birth", "Personal",
                CanonicalFieldValueKind.Country, CanonicalFieldSensitivity.Sensitive,
                ["country of birth", "birth country"], ["country of birth", "birth country"]),
            D("personal.nationality", "Nationality", "Personal",
                CanonicalFieldValueKind.Nationality, CanonicalFieldSensitivity.Sensitive,
                ["nationality", "citizenship", "country of citizenship"],
                ["nationality", "citizenship", "country of citizenship"]),
            D("personal.previous_nationality", "Previous Nationality", "Personal",
                CanonicalFieldValueKind.Nationality, CanonicalFieldSensitivity.Sensitive,
                ["previous nationality", "former nationality", "previous citizenship"],
                ["previous nationality", "former nationality", "previous citizenship"]),
            D("personal.religion", "Religion", "Personal", CanonicalFieldValueKind.Text,
                CanonicalFieldSensitivity.HighlySensitive, ["religion", "faith"],
                ["religion", "faith"]),
            D("professional.occupation", "Occupation", "Professional",
                CanonicalFieldValueKind.Text, CanonicalFieldSensitivity.Sensitive,
                ["occupation", "profession", "job title"],
                ["occupation", "profession", "job title"]),
            D("professional.employer", "Employer", "Professional",
                CanonicalFieldValueKind.Text, CanonicalFieldSensitivity.Sensitive,
                ["employer", "company name", "organization name", "organisation name"],
                ["employer", "company name", "organization name", "organisation name"]),
            D("professional.designation", "Designation", "Professional",
                CanonicalFieldValueKind.Text, CanonicalFieldSensitivity.Sensitive,
                ["designation", "position", "work designation"],
                ["designation", "position", "work designation"]),

            D("passport.number", "Passport Number", "Passport",
                CanonicalFieldValueKind.Identifier, CanonicalFieldSensitivity.HighlySensitive,
                ["passport number", "passport no", "passport no.", "passport #",
                 "ppt number", "ppt no", "travel document number", "document number",
                 "passportnumber"],
                ["passport number", "passport no", "passport #", "ppt number",
                 "ppt no", "travel document number", "passportnumber"],
                ["application", "visa", "booking", "reference", "employee", "national id"]),
            D("passport.type", "Passport Type", "Passport", CanonicalFieldValueKind.Text,
                CanonicalFieldSensitivity.Sensitive,
                ["passport type", "travel document type", "document type"],
                ["passport type", "travel document type"]),
            D("passport.issue_date", "Passport Issue Date", "Passport",
                CanonicalFieldValueKind.Date, CanonicalFieldSensitivity.HighlySensitive,
                ["passport issue date", "date of issue", "issue date"],
                ["passport issue date"]),
            D("passport.expiry_date", "Passport Expiry Date", "Passport",
                CanonicalFieldValueKind.Date, CanonicalFieldSensitivity.HighlySensitive,
                ["passport expiry date", "passport expiration date", "date of expiry",
                 "expiry date", "expiration date", "valid until"],
                ["passport expiry date", "passport expiration date"]),
            D("passport.place_of_issue", "Passport Place of Issue", "Passport",
                CanonicalFieldValueKind.Text, CanonicalFieldSensitivity.Sensitive,
                ["passport place of issue", "place of issue", "issue place"],
                ["passport place of issue"]),
            D("passport.country_of_issue", "Passport Country of Issue", "Passport",
                CanonicalFieldValueKind.Country, CanonicalFieldSensitivity.Sensitive,
                ["passport country of issue", "country of issue", "issuing country"],
                ["passport country of issue"]),
            D("passport.issuing_authority", "Issuing Authority", "Passport",
                CanonicalFieldValueKind.Text, CanonicalFieldSensitivity.Sensitive,
                ["issuing authority", "passport authority", "authority"],
                ["passport issuing authority", "passport authority"]),
            D("passport.old_number", "Old Passport Number", "Passport",
                CanonicalFieldValueKind.Identifier, CanonicalFieldSensitivity.HighlySensitive,
                ["old passport number", "previous passport number", "former passport number"],
                ["old passport number", "previous passport number", "former passport number"]),
            D("identity.national_id_number", "National ID Number", "Identity",
                CanonicalFieldValueKind.Identifier, CanonicalFieldSensitivity.HighlySensitive,
                ["national id number", "national identification number", "national id",
                 "identity card"],
                ["national id number", "national identification number", "national id",
                 "identity card"],
                ["passport", "application", "visa", "booking"]),

            D("contact.email", "Email", "Contact", CanonicalFieldValueKind.Email,
                CanonicalFieldSensitivity.HighlySensitive,
                ["email", "email address", "primary email", "contact email"],
                ["email", "email address", "primary email", "contact email"]),
            D("contact.alternate_email", "Alternate Email", "Contact",
                CanonicalFieldValueKind.Email, CanonicalFieldSensitivity.HighlySensitive,
                ["alternate email", "alternative email", "secondary email"],
                ["alternate email", "alternative email", "secondary email"]),
            D("contact.mobile", "Mobile Number", "Contact", CanonicalFieldValueKind.Phone,
                CanonicalFieldSensitivity.HighlySensitive,
                ["mobile number", "mobile", "mobile phone", "cell phone", "cell number",
                 "cellphone", "phone", "phone number", "primary phone", "contact number"],
                ["mobile number", "mobile", "mobile phone", "cell phone", "cell number",
                 "cellphone", "primary phone"]),
            D("contact.alternate_mobile", "Alternate Mobile Number", "Contact",
                CanonicalFieldValueKind.Phone, CanonicalFieldSensitivity.HighlySensitive,
                ["alternate mobile number", "alternative phone", "secondary phone",
                 "alternate contact number"],
                ["alternate mobile number", "alternative phone", "secondary phone",
                 "alternate contact number"]),
            D("contact.country_calling_code", "Country Calling Code", "Contact",
                CanonicalFieldValueKind.Phone, CanonicalFieldSensitivity.Sensitive,
                ["country calling code", "country code", "dialing code", "dialling code"],
                ["country calling code", "phone country code", "dialing code", "dialling code"]),
            D("contact.landline", "Landline Number", "Contact",
                CanonicalFieldValueKind.Phone, CanonicalFieldSensitivity.HighlySensitive,
                ["landline number", "landline", "telephone number"],
                ["landline number", "landline", "home phone", "office phone"]),

            D("address.line1", "Address Line 1", "Address", CanonicalFieldValueKind.Address,
                CanonicalFieldSensitivity.HighlySensitive,
                ["address line 1", "address 1", "address line one"],
                ["address line 1", "address 1", "address line one"]),
            D("address.line2", "Address Line 2", "Address", CanonicalFieldValueKind.Address,
                CanonicalFieldSensitivity.HighlySensitive,
                ["address line 2", "address 2", "address line two"],
                ["address line 2", "address 2", "address line two"]),
            D("address.street", "Street", "Address", CanonicalFieldValueKind.Address,
                CanonicalFieldSensitivity.HighlySensitive,
                ["street", "street name", "road"], ["street", "street name", "road"]),
            D("address.locality", "Locality", "Address", CanonicalFieldValueKind.Address,
                CanonicalFieldSensitivity.HighlySensitive,
                ["locality", "neighbourhood", "neighborhood"],
                ["locality", "neighbourhood", "neighborhood"]),
            D("address.city", "Address City", "Address", CanonicalFieldValueKind.Address,
                CanonicalFieldSensitivity.HighlySensitive,
                ["address city", "residential city", "city of residence"],
                ["address city", "residential city", "city of residence"]),
            D("address.state", "State", "Address", CanonicalFieldValueKind.Address,
                CanonicalFieldSensitivity.HighlySensitive,
                ["state", "address state", "state of residence"],
                ["state", "address state", "state of residence"]),
            D("address.province", "Province", "Address", CanonicalFieldValueKind.Address,
                CanonicalFieldSensitivity.HighlySensitive,
                ["province", "address province"], ["province", "address province"]),
            D("address.district", "District", "Address", CanonicalFieldValueKind.Address,
                CanonicalFieldSensitivity.HighlySensitive,
                ["district", "address district"], ["district", "address district"]),
            D("address.postal_code", "Postal Code / PIN Code", "Address",
                CanonicalFieldValueKind.Identifier, CanonicalFieldSensitivity.HighlySensitive,
                ["postal code", "postcode", "zip code", "pin code", "pincode"],
                ["postal code", "postcode", "zip code", "pin code", "pincode"]),
            D("address.country", "Address Country", "Address",
                CanonicalFieldValueKind.Country, CanonicalFieldSensitivity.HighlySensitive,
                ["address country", "country of residence", "residential country"],
                ["address country", "country of residence", "residential country"]),

            D("travel.arrival_date", "Arrival Date", "Travel", CanonicalFieldValueKind.Date,
                CanonicalFieldSensitivity.Sensitive, ["arrival date", "date of arrival"],
                ["arrival date", "date of arrival"]),
            D("travel.departure_date", "Departure Date", "Travel",
                CanonicalFieldValueKind.Date, CanonicalFieldSensitivity.Sensitive,
                ["departure date", "date of departure"],
                ["departure date", "date of departure"]),
            D("travel.purpose_of_visit", "Purpose of Visit", "Travel",
                CanonicalFieldValueKind.Text, CanonicalFieldSensitivity.Sensitive,
                ["purpose of visit", "travel purpose", "visit purpose"],
                ["purpose of visit", "travel purpose", "visit purpose"]),
            D("travel.port_of_arrival", "Port of Arrival", "Travel",
                CanonicalFieldValueKind.Text, CanonicalFieldSensitivity.Sensitive,
                ["port of arrival", "arrival port"], ["port of arrival", "arrival port"]),
            D("travel.port_of_departure", "Port of Departure", "Travel",
                CanonicalFieldValueKind.Text, CanonicalFieldSensitivity.Sensitive,
                ["port of departure", "departure port"],
                ["port of departure", "departure port"]),
            D("travel.flight_number", "Flight Number", "Travel",
                CanonicalFieldValueKind.Identifier, CanonicalFieldSensitivity.Sensitive,
                ["flight number", "flight no", "flight #"],
                ["flight number", "flight no", "flight #"]),
            D("travel.airline", "Airline", "Travel", CanonicalFieldValueKind.Text,
                CanonicalFieldSensitivity.Sensitive, ["airline", "carrier"],
                ["airline", "carrier"]),
            D("travel.hotel_name", "Hotel Name", "Travel", CanonicalFieldValueKind.Text,
                CanonicalFieldSensitivity.Sensitive,
                ["hotel name", "accommodation name"], ["hotel name", "accommodation name"]),
            D("travel.hotel_address", "Hotel Address", "Travel",
                CanonicalFieldValueKind.Address, CanonicalFieldSensitivity.Sensitive,
                ["hotel address", "accommodation address"],
                ["hotel address", "accommodation address"]),
            D("travel.destination_city", "Destination City", "Travel",
                CanonicalFieldValueKind.Text, CanonicalFieldSensitivity.Sensitive,
                ["destination city", "city of destination"],
                ["destination city", "city of destination"]),
            D("travel.destination_country", "Destination Country", "Travel",
                CanonicalFieldValueKind.Country, CanonicalFieldSensitivity.Sensitive,
                ["destination country", "country of destination"],
                ["destination country", "country of destination"]),
            D("travel.duration_of_stay", "Duration of Stay", "Travel",
                CanonicalFieldValueKind.Number, CanonicalFieldSensitivity.Sensitive,
                ["duration of stay", "stay duration", "length of stay"],
                ["duration of stay", "stay duration", "length of stay"]),

            D("emergency.name", "Emergency Contact Name", "Emergency Contact",
                CanonicalFieldValueKind.Name, CanonicalFieldSensitivity.HighlySensitive,
                ["emergency contact name", "emergency name"],
                ["emergency contact name", "emergency name"]),
            D("emergency.relationship", "Emergency Contact Relationship", "Emergency Contact",
                CanonicalFieldValueKind.Text, CanonicalFieldSensitivity.Sensitive,
                ["emergency contact relationship", "emergency relationship",
                 "relationship to emergency contact"],
                ["emergency contact relationship", "emergency relationship",
                 "relationship to emergency contact"]),
            D("emergency.phone", "Emergency Contact Phone", "Emergency Contact",
                CanonicalFieldValueKind.Phone, CanonicalFieldSensitivity.HighlySensitive,
                ["emergency contact phone", "emergency phone", "emergency contact number"],
                ["emergency contact phone", "emergency phone", "emergency contact number"]),
            D("emergency.email", "Emergency Contact Email", "Emergency Contact",
                CanonicalFieldValueKind.Email, CanonicalFieldSensitivity.HighlySensitive,
                ["emergency contact email", "emergency email"],
                ["emergency contact email", "emergency email"]),
            D("emergency.address", "Emergency Contact Address", "Emergency Contact",
                CanonicalFieldValueKind.Address, CanonicalFieldSensitivity.HighlySensitive,
                ["emergency contact address", "emergency address"],
                ["emergency contact address", "emergency address"]),
        ];
    }

    private static CanonicalFieldDefinition D(
        string id,
        string displayName,
        string fieldGroup,
        CanonicalFieldValueKind valueKind,
        CanonicalFieldSensitivity sensitivity,
        IReadOnlyList<string> sourceAliases,
        IReadOnlyList<string> targetAliases,
        IReadOnlyList<string>? blockingTargetTokens = null)
    {
        return new CanonicalFieldDefinition(
            id,
            displayName,
            fieldGroup,
            valueKind,
            sensitivity,
            Array.AsReadOnly(sourceAliases.Distinct(StringComparer.Ordinal).ToArray()),
            Array.AsReadOnly(targetAliases.Distinct(StringComparer.Ordinal).ToArray()),
            Array.AsReadOnly(
                (blockingTargetTokens ?? Array.Empty<string>())
                .Select(DeterministicTextNormalizer.Normalize)
                .Where(token => token.Length > 0)
                .Distinct(StringComparer.Ordinal)
                .ToArray()));
    }
}
