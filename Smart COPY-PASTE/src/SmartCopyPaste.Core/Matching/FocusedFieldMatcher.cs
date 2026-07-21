using SmartCopyPaste.Core.Catalog;
using SmartCopyPaste.Core.Normalization;
using SmartCopyPaste.Core.Security;

namespace SmartCopyPaste.Core.Matching;

/// <summary>
/// Explainable, deterministic target-field matcher. Exact aliases remain the
/// only general-purpose automatic path; bounded contextual rules are used to
/// rank a small, related picker set without fuzzy spelling guesses.
/// </summary>
public sealed class FocusedFieldMatcher
{
    public const int AutomaticPasteThreshold = 90;
    public const int RequiredWinnerMargin = 10;

    private const int MaximumAvailableFields = 128;
    private const int MaximumRankedCandidates = 12;
    private const int MinimumRankedCandidateScore = 60;
    private const int RankedCandidateScoreWindow = 14;

    private static readonly HashSet<string> ContextStopTokens =
        new(StringComparer.Ordinal)
        {
            "a",
            "an",
            "and",
            "applicant",
            "as",
            "code",
            "contact",
            "date",
            "details",
            "field",
            "holder",
            "info",
            "information",
            "input",
            "name",
            "number",
            "of",
            "passenger",
            "per",
            "primary",
            "the",
            "traveler",
            "traveller",
            "value",
            "your",
        };

    private readonly CanonicalFieldCatalog _catalog;

    public FocusedFieldMatcher(CanonicalFieldCatalog? catalog = null)
    {
        _catalog = catalog ?? CanonicalFieldCatalog.Default;
    }

    public FieldMatchResult Match(
        FocusedFieldContext context,
        IEnumerable<string> availableCanonicalFieldIds)
    {
        ArgumentNullException.ThrowIfNull(context);
        return Match(
            context,
            availableCanonicalFieldIds,
            context.SavedCanonicalFieldId);
    }

    public FieldMatchResult Match(
        FocusedFieldContext context,
        IEnumerable<string> availableCanonicalFieldIds,
        string? savedCanonicalFieldId)
    {
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(availableCanonicalFieldIds);

        if (!TryMaterializeAvailableFields(
            availableCanonicalFieldIds,
            out HashSet<string> available))
        {
            return Blocked("AVAILABLE_FIELDS_INVALID");
        }

        FieldMatchResult? blocked = CheckProtectedControl(context);
        if (blocked is not null)
        {
            return blocked;
        }

        if (!string.IsNullOrWhiteSpace(savedCanonicalFieldId))
        {
            return MatchSavedMapping(savedCanonicalFieldId, available);
        }

        List<MetadataSignal> signals = CreateMetadataSignals(context);
        var exactCandidates =
            new Dictionary<string, CandidateScore>(StringComparer.Ordinal);
        foreach (MetadataSignal signal in signals)
        {
            AddExactEvidence(signal, exactCandidates, allowedFieldIds: null);
        }

        if (exactCandidates.Count > 0)
        {
            FieldMatchResult exactMatch = ResolveExactMatch(
                exactCandidates,
                available,
                CombinedMetadata(signals));
            if (exactMatch.CanonicalFieldId is not null &&
                HasQualifiedSectionConflict(
                    signals,
                    exactMatch.CanonicalFieldId))
            {
                return exactMatch with
                {
                    Status = FieldMatchStatus.Ambiguous,
                    CanonicalFieldId = null,
                    ReasonCode = "SECTION_CONTEXT_CONFLICT",
                };
            }

            return exactMatch;
        }

        FieldCandidateRankingResult ranking = RankCandidates(
            context with { SavedCanonicalFieldId = null },
            available);
        return ResolveRankedFallback(ranking);
    }

    /// <summary>
    /// Returns only related fields that are present in the active profile.
    /// An empty result intentionally tells the UI to offer its full searchable
    /// fallback instead of pretending unrelated fields are relevant.
    /// </summary>
    public FieldCandidateRankingResult RankCandidates(
        FocusedFieldContext context,
        IEnumerable<string> availableCanonicalFieldIds,
        int maximumCandidates = 6)
    {
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(availableCanonicalFieldIds);
        ArgumentOutOfRangeException.ThrowIfLessThan(maximumCandidates, 1);
        ArgumentOutOfRangeException.ThrowIfGreaterThan(
            maximumCandidates,
            MaximumRankedCandidates);

        if (!TryMaterializeAvailableFields(
            availableCanonicalFieldIds,
            out HashSet<string> available))
        {
            return BlockedRanking("AVAILABLE_FIELDS_INVALID");
        }

        FieldMatchResult? protectedControl = CheckProtectedControl(context);
        if (protectedControl is not null)
        {
            return BlockedRanking(protectedControl.ReasonCode);
        }

        if (!string.IsNullOrWhiteSpace(context.SavedCanonicalFieldId))
        {
            return RankSavedMapping(context.SavedCanonicalFieldId, available);
        }

        List<MetadataSignal> signals = CreateMetadataSignals(context);
        if (signals.Count == 0)
        {
            return NoRelatedCandidates("NO_TARGET_METADATA");
        }

        var candidates =
            new Dictionary<string, CandidateScore>(StringComparer.Ordinal);
        foreach (MetadataSignal signal in signals)
        {
            AddExactEvidence(signal, candidates, available);
        }

        PhoneIntent phoneIntent = DetectPhoneIntent(signals);
        if (phoneIntent == PhoneIntent.UnsupportedSubcomponent)
        {
            return BlockedRanking("PHONE_SUBCOMPONENT_UNSUPPORTED");
        }

        if (phoneIntent != PhoneIntent.None)
        {
            AddPhoneIntentEvidence(phoneIntent, signals, available, candidates);
        }
        else
        {
            AddContextualEvidence(signals, available, candidates);
        }

        _ = candidates.RemoveWhere(pair =>
            HasQualifiedSectionConflict(signals, pair.Key));

        string combinedMetadata = CombinedMetadata(signals);
        int blockedCandidateCount = candidates.RemoveWhere(pair =>
            HasBlockingTargetToken(pair.Key, combinedMetadata));

        CandidateScore[] ranked = candidates.Values
            .Select(candidate => candidate.WithFinalScore())
            .Where(candidate =>
                candidate.FinalScore >= MinimumRankedCandidateScore)
            .OrderByDescending(candidate => candidate.FinalScore)
            .ThenBy(candidate => candidate.CanonicalFieldId, StringComparer.Ordinal)
            .ToArray();

        if (ranked.Length == 0)
        {
            return blockedCandidateCount > 0
                ? BlockedRanking("CONFLICTING_TARGET_TOKEN")
                : NoRelatedCandidates("NO_RELATED_CANDIDATES");
        }

        int minimumWindowScore =
            Math.Max(
                MinimumRankedCandidateScore,
                ranked[0].FinalScore - RankedCandidateScoreWindow);
        RankedFieldCandidate[] selected = ranked
            .Where(candidate => candidate.FinalScore >= minimumWindowScore)
            .Take(maximumCandidates)
            .Select(ToRankedCandidate)
            .ToArray();

        string reasonCode = phoneIntent == PhoneIntent.Generic
            ? "GENERIC_TELEPHONE_CANDIDATES_RANKED"
            : "RELATED_CANDIDATES_RANKED";
        return new FieldCandidateRankingResult(
            FieldCandidateRankingStatus.Ranked,
            Array.AsReadOnly(selected),
            reasonCode);
    }

    private static FieldMatchResult MatchSavedMapping(
        string savedCanonicalFieldId,
        HashSet<string> available)
    {
        if (savedCanonicalFieldId.Length > 96)
        {
            return Blocked("SAVED_MAPPING_INVALID");
        }

        var savedEvidence = new FieldMatchEvidence(
            savedCanonicalFieldId,
            MatchEvidenceSource.SavedMapping,
            100,
            "saved-exact-signature");
        if (!available.Contains(savedCanonicalFieldId))
        {
            return new FieldMatchResult(
                FieldMatchStatus.MissingValue,
                savedCanonicalFieldId,
                100,
                Array.AsReadOnly([savedEvidence]),
                "SAVED_MAPPING_VALUE_UNAVAILABLE");
        }

        return new FieldMatchResult(
            FieldMatchStatus.Matched,
            savedCanonicalFieldId,
            100,
            Array.AsReadOnly([savedEvidence]),
            "SAVED_MAPPING");
    }

    private FieldCandidateRankingResult RankSavedMapping(
        string savedCanonicalFieldId,
        HashSet<string> available)
    {
        if (savedCanonicalFieldId.Length > 96)
        {
            return BlockedRanking("SAVED_MAPPING_INVALID");
        }

        if (!available.Contains(savedCanonicalFieldId))
        {
            return NoRelatedCandidates("SAVED_MAPPING_VALUE_UNAVAILABLE");
        }

        string displayName = _catalog.TryGetDefinition(
            savedCanonicalFieldId,
            out CanonicalFieldDefinition? definition)
            && definition is not null
                ? definition.DisplayName
                : savedCanonicalFieldId;
        var evidence = new FieldMatchEvidence(
            savedCanonicalFieldId,
            MatchEvidenceSource.SavedMapping,
            100,
            "saved-exact-signature");
        var candidate = new RankedFieldCandidate(
            savedCanonicalFieldId,
            displayName,
            100,
            FieldCandidateConfidence.High,
            "SAVED_MAPPING",
            Array.AsReadOnly([evidence]));
        return new FieldCandidateRankingResult(
            FieldCandidateRankingStatus.Ranked,
            Array.AsReadOnly([candidate]),
            "SAVED_MAPPING");
    }

    private FieldMatchResult ResolveExactMatch(
        IReadOnlyDictionary<string, CandidateScore> candidates,
        HashSet<string> available,
        string combinedMetadata)
    {
        CandidateScore[] ranked = candidates.Values
            .Select(candidate => candidate.WithFinalScore())
            .OrderByDescending(candidate => candidate.FinalScore)
            .ThenBy(candidate => candidate.CanonicalFieldId, StringComparer.Ordinal)
            .ToArray();
        CandidateScore winner = ranked[0];
        FieldMatchEvidence[] allEvidence = OrderEvidence(
            ranked.SelectMany(candidate => candidate.Evidence));

        if (HasBlockingTargetToken(winner.CanonicalFieldId, combinedMetadata))
        {
            return new FieldMatchResult(
                FieldMatchStatus.Ambiguous,
                null,
                winner.FinalScore,
                Array.AsReadOnly(allEvidence),
                "CONFLICTING_TARGET_TOKEN");
        }

        if (ranked.Length > 1
            && winner.FinalScore - ranked[1].FinalScore < RequiredWinnerMargin)
        {
            return new FieldMatchResult(
                FieldMatchStatus.Ambiguous,
                null,
                winner.FinalScore,
                Array.AsReadOnly(allEvidence),
                "MATCH_SCORE_NOT_UNIQUE");
        }

        if (!available.Contains(winner.CanonicalFieldId))
        {
            return new FieldMatchResult(
                FieldMatchStatus.MissingValue,
                winner.CanonicalFieldId,
                winner.FinalScore,
                Array.AsReadOnly(allEvidence),
                "MATCHED_VALUE_UNAVAILABLE");
        }

        if (winner.FinalScore < AutomaticPasteThreshold)
        {
            return new FieldMatchResult(
                FieldMatchStatus.Unknown,
                winner.CanonicalFieldId,
                winner.FinalScore,
                Array.AsReadOnly(allEvidence),
                "CONFIDENCE_BELOW_AUTOMATIC_THRESHOLD");
        }

        return new FieldMatchResult(
            FieldMatchStatus.Matched,
            winner.CanonicalFieldId,
            winner.FinalScore,
            Array.AsReadOnly(allEvidence),
            "UNIQUE_EXACT_MATCH");
    }

    private static FieldMatchResult ResolveRankedFallback(
        FieldCandidateRankingResult ranking)
    {
        if (ranking.Status == FieldCandidateRankingStatus.Blocked)
        {
            return Blocked(ranking.ReasonCode);
        }

        if (!ranking.HasRelatedCandidates)
        {
            return Unknown(
                ranking.ReasonCode,
                Array.Empty<FieldMatchEvidence>());
        }

        RankedFieldCandidate winner = ranking.Candidates[0];
        FieldMatchEvidence[] allEvidence = OrderEvidence(
            ranking.Candidates.SelectMany(candidate => candidate.Evidence));

        if (ranking.Candidates.Count > 1
            && winner.Score - ranking.Candidates[1].Score
                < RequiredWinnerMargin)
        {
            return new FieldMatchResult(
                FieldMatchStatus.Ambiguous,
                null,
                winner.Score,
                Array.AsReadOnly(allEvidence),
                "MATCH_SCORE_NOT_UNIQUE");
        }

        if (winner.Score >= AutomaticPasteThreshold
            && IsSafeSpecificRelationship(winner.ReasonCode))
        {
            return new FieldMatchResult(
                FieldMatchStatus.Matched,
                winner.CanonicalFieldId,
                winner.Score,
                Array.AsReadOnly(allEvidence),
                "UNIQUE_SPECIFIC_RELATIONSHIP");
        }

        return new FieldMatchResult(
            FieldMatchStatus.Unknown,
            winner.CanonicalFieldId,
            winner.Score,
            Array.AsReadOnly(allEvidence),
            "RELATED_CANDIDATE_REQUIRES_CONFIRMATION");
    }

    private static bool IsSafeSpecificRelationship(string reasonCode) =>
        reasonCode is "ALTERNATE_MOBILE_RELATED"
            or "COUNTRY_CALLING_CODE_RELATED"
            or "EMERGENCY_PHONE_RELATED"
            or "SPECIFIC_LANDLINE_RELATED"
            or "SPECIFIC_MOBILE_RELATED";

    private static FieldMatchResult? CheckProtectedControl(
        FocusedFieldContext context)
    {
        if (LengthExceeds(context.ProcessName, 128)
            || LengthExceeds(context.ControlType, 128)
            || LengthExceeds(context.AccessibleName, 512)
            || LengthExceeds(context.AutomationId, 512)
            || LengthExceeds(context.HelpText, 512)
            || LengthExceeds(context.ClassName, 256)
            || LengthExceeds(context.Placeholder, 512)
            || LengthExceeds(context.SectionHeading, 512)
            || LengthExceeds(context.InputType, 128)
            || LengthExceeds(context.FormatHint, 512))
        {
            return Blocked("FIELD_METADATA_TOO_LARGE");
        }

        if (context.IsPassword)
        {
            return Blocked("PASSWORD_CONTROL");
        }

        if (!context.IsEnabled)
        {
            return Blocked("CONTROL_DISABLED");
        }

        if (context.IsReadOnly)
        {
            return Blocked("CONTROL_READ_ONLY");
        }

        string controlType =
            DeterministicTextNormalizer.Normalize(context.ControlType);
        HashSet<string> controlTokens = ToTokens(controlType);
        if (controlTokens.Overlaps(
            ["button", "document", "hyperlink", "menu", "password"]))
        {
            return Blocked("UNSUPPORTED_CONTROL_TYPE");
        }

        string directFieldMetadata = DeterministicTextNormalizer.Normalize(
            string.Join(
                ' ',
                context.AccessibleName,
                context.AutomationId,
                context.HelpText,
                context.ClassName,
                context.Placeholder,
                context.InputType,
                context.FormatHint));
        string allFieldMetadata = DeterministicTextNormalizer.Normalize(
            $"{directFieldMetadata} {context.SectionHeading}");
        string inputType =
            DeterministicTextNormalizer.Normalize(context.InputType);
        HashSet<string> directTokens = ToTokens(directFieldMetadata);
        if (ProtectedAuthenticationFieldClassifier.IsProtected(
                context.AccessibleName,
                context.AutomationId,
                context.HelpText,
                context.ClassName,
                context.Placeholder,
                context.InputType,
                context.FormatHint) ||
            ContainsPhrase(directFieldMetadata, "choose file") ||
            directTokens.Contains("file") &&
                directTokens.Overlaps(["browse", "choose", "select", "upload"]) ||
            inputType is "date" or "file" or "password")
        {
            return Blocked("PROTECTED_CONTROL_METADATA");
        }

        if (ToTokens(allFieldMetadata).Overlaps(["captcha", "recaptcha"]) ||
            ContainsPhrase(allFieldMetadata, "i am not a robot") ||
            ContainsPhrase(allFieldMetadata, "security challenge"))
        {
            return Blocked("PROTECTED_CONTROL_METADATA");
        }

        return null;
    }

    private static List<MetadataSignal> CreateMetadataSignals(
        FocusedFieldContext context)
    {
        var signals = new List<MetadataSignal>(5);
        AddMetadataSignal(
            signals,
            context.AccessibleName,
            MatchEvidenceSource.AccessibleName,
            95,
            88,
            "exact-accessible-name",
            "EXACT_ACCESSIBLE_NAME");
        AddMetadataSignal(
            signals,
            context.AutomationId,
            MatchEvidenceSource.AutomationId,
            90,
            84,
            "exact-automation-id",
            "EXACT_AUTOMATION_ID");
        AddMetadataSignal(
            signals,
            context.HelpText,
            MatchEvidenceSource.HelpText,
            80,
            74,
            "exact-help-text",
            "EXACT_HELP_TEXT");
        AddMetadataSignal(
            signals,
            context.Placeholder,
            MatchEvidenceSource.Placeholder,
            86,
            80,
            "exact-placeholder",
            "EXACT_PLACEHOLDER");
        AddMetadataSignal(
            signals,
            context.SectionHeading,
            MatchEvidenceSource.SectionHeading,
            70,
            65,
            "exact-section-heading",
            "EXACT_SECTION_HEADING");
        return signals;
    }

    private static void AddMetadataSignal(
        ICollection<MetadataSignal> signals,
        string value,
        MatchEvidenceSource source,
        int exactScore,
        int contextualScore,
        string exactRule,
        string exactReasonCode)
    {
        string normalized = TargetMetadataNormalizer.NormalizeLabel(value);
        if (normalized.Length > 0)
        {
            signals.Add(new MetadataSignal(
                normalized,
                source,
                exactScore,
                contextualScore,
                exactRule,
                exactReasonCode));
        }
    }

    private void AddExactEvidence(
        MetadataSignal signal,
        IDictionary<string, CandidateScore> candidates,
        HashSet<string>? allowedFieldIds)
    {
        AliasMatch match = _catalog.ResolveTarget(signal.Normalized);
        foreach (string candidateId in match.CandidateFieldIds)
        {
            if (allowedFieldIds is not null
                && !allowedFieldIds.Contains(candidateId))
            {
                continue;
            }

            CandidateScore candidate = GetOrAddCandidate(
                candidateId,
                candidates);
            candidate.AddEvidence(
                new FieldMatchEvidence(
                    candidateId,
                    signal.Source,
                    signal.ExactScore,
                    match.Status == AliasMatchStatus.Ambiguous
                        ? $"{signal.ExactRule}-ambiguous-alias"
                        : signal.ExactRule),
                signal.ExactReasonCode);
        }
    }

    private void AddContextualEvidence(
        List<MetadataSignal> signals,
        HashSet<string> available,
        IDictionary<string, CandidateScore> candidates)
    {
        foreach (CanonicalFieldDefinition definition in _catalog.Definitions)
        {
            if (!available.Contains(definition.Id))
            {
                continue;
            }

            foreach (MetadataSignal signal in signals)
            {
                int score = BestContextualAliasScore(
                    signal.Normalized,
                    definition.TargetAliases,
                    signal.ContextualScore);
                if (score < MinimumRankedCandidateScore)
                {
                    continue;
                }

                GetOrAddCandidate(definition.Id, candidates)
                    .AddEvidence(
                        new FieldMatchEvidence(
                            definition.Id,
                            signal.Source,
                            score,
                            $"contextual-{EvidenceSourceCode(signal.Source)}"),
                        "CONTEXTUAL_ALIAS_TOKENS");
            }
        }

        MetadataSignal? section = signals.FirstOrDefault(
            signal => signal.Source == MatchEvidenceSource.SectionHeading);
        if (section is null)
        {
            return;
        }

        foreach (MetadataSignal label in signals.Where(
            signal => signal.Source != MatchEvidenceSource.SectionHeading))
        {
            foreach (CanonicalFieldDefinition definition in _catalog.Definitions)
            {
                if (!available.Contains(definition.Id))
                {
                    continue;
                }

                int score = BestSectionContextualAliasScore(
                    section.Normalized,
                    label.Normalized,
                    definition.TargetAliases,
                    89);
                if (score < MinimumRankedCandidateScore)
                {
                    continue;
                }

                GetOrAddCandidate(definition.Id, candidates)
                    .AddEvidence(
                        new FieldMatchEvidence(
                            definition.Id,
                            MatchEvidenceSource.ContextualMetadata,
                            score,
                            "section-and-label-context"),
                        "SECTION_CONTEXT");
            }
        }
    }

    private static int BestSectionContextualAliasScore(
        string normalizedSection,
        string normalizedLabel,
        IEnumerable<string> aliases,
        int baseScore)
    {
        HashSet<string> labelTokens = ToTokens(normalizedLabel)
            .Where(token => !ContextStopTokens.Contains(token))
            .ToHashSet(StringComparer.Ordinal);
        if (labelTokens.Count == 0)
        {
            return 0;
        }

        string combined = $"{normalizedSection} {normalizedLabel}";
        int best = 0;
        foreach (string alias in aliases)
        {
            string normalizedAlias =
                DeterministicTextNormalizer.Normalize(alias);
            HashSet<string> aliasTokens = ToTokens(normalizedAlias)
                .Where(token => !ContextStopTokens.Contains(token))
                .ToHashSet(StringComparer.Ordinal);
            if (!aliasTokens.Overlaps(labelTokens))
            {
                continue;
            }

            best = Math.Max(
                best,
                CalculateContextualScore(
                    combined,
                    normalizedAlias,
                    baseScore));
        }

        return best;
    }

    private static int BestContextualAliasScore(
        string normalizedMetadata,
        IEnumerable<string> aliases,
        int baseScore)
    {
        int best = 0;
        foreach (string alias in aliases)
        {
            string normalizedAlias =
                DeterministicTextNormalizer.Normalize(alias);
            if (normalizedAlias == normalizedMetadata)
            {
                continue;
            }

            best = Math.Max(
                best,
                CalculateContextualScore(
                    normalizedMetadata,
                    normalizedAlias,
                    baseScore));
        }

        return best;
    }

    private static int CalculateContextualScore(
        string normalizedMetadata,
        string normalizedAlias,
        int baseScore)
    {
        HashSet<string> metadataTokens = ToTokens(normalizedMetadata);
        HashSet<string> aliasTokens = ToTokens(normalizedAlias);
        if (metadataTokens.Count == 0 || aliasTokens.Count == 0)
        {
            return 0;
        }

        HashSet<string> discriminativeAlias = aliasTokens
            .Where(token => !ContextStopTokens.Contains(token))
            .ToHashSet(StringComparer.Ordinal);
        HashSet<string> discriminativeMetadata = metadataTokens
            .Where(token => !ContextStopTokens.Contains(token))
            .ToHashSet(StringComparer.Ordinal);
        if (discriminativeAlias.Count == 0
            || discriminativeMetadata.Count == 0)
        {
            return 0;
        }

        int discriminativeOverlap = discriminativeAlias.Count(
            discriminativeMetadata.Contains);
        if (discriminativeOverlap == 0)
        {
            return 0;
        }

        if (aliasTokens.IsSubsetOf(metadataTokens))
        {
            return baseScore;
        }

        if (metadataTokens.IsSubsetOf(aliasTokens))
        {
            return Math.Max(
                MinimumRankedCandidateScore,
                baseScore - 8);
        }

        double coverage =
            (double)discriminativeOverlap / discriminativeAlias.Count;
        if (coverage >= 0.75)
        {
            return Math.Max(
                MinimumRankedCandidateScore,
                baseScore - 8);
        }

        if (coverage >= 0.5
            && (discriminativeOverlap >= 2
                || discriminativeAlias.Count <= 2))
        {
            return Math.Max(
                MinimumRankedCandidateScore,
                baseScore - 15);
        }

        return 0;
    }

    private static PhoneIntent DetectPhoneIntent(
        List<MetadataSignal> signals)
    {
        HashSet<string> tokens = signals
            .SelectMany(signal => ToTokens(signal.Normalized))
            .ToHashSet(StringComparer.Ordinal);
        bool hasPhoneWord = tokens.Overlaps(
            ["cell", "cellular", "cellphone", "mobile", "phone", "tel", "telephone"]);
        bool hasContactNumber =
            tokens.Contains("contact") && tokens.Contains("number");
        bool saysCallingCode = signals.Any(signal =>
        {
            if (signal.Source is not (
                MatchEvidenceSource.AccessibleName or
                MatchEvidenceSource.AutomationId or
                MatchEvidenceSource.Placeholder))
            {
                return false;
            }

            HashSet<string> directTokens = ToTokens(signal.Normalized);
            bool fullNumberInstruction =
                directTokens.Overlaps(
                    ["add", "include", "included", "includes", "including",
                     "plus", "prefix", "using", "with"]);
            return !fullNumberInstruction &&
                directTokens.Contains("code") &&
                (directTokens.Overlaps(["calling", "dialing", "dialling"]) ||
                 directTokens.Contains("country"));
        });
        if (!hasPhoneWord && !hasContactNumber && !saysCallingCode)
        {
            return PhoneIntent.None;
        }

        bool saysMobile =
            tokens.Overlaps(["cell", "cellular", "cellphone", "mobile"]);
        bool saysLandline = tokens.Contains("landline")
            || tokens.Overlaps(["home", "office"]) && hasPhoneWord;
        bool saysAlternate =
            tokens.Overlaps(["alternate", "alternative", "secondary"]);
        bool saysSubcomponent =
            tokens.Overlaps(["ext", "extension", "extn", "prefix"]) ||
            tokens.Contains("area") && tokens.Contains("code");
        if (saysSubcomponent)
        {
            return PhoneIntent.UnsupportedSubcomponent;
        }

        if (saysMobile && saysLandline)
        {
            return PhoneIntent.Generic;
        }

        bool saysEmergency = tokens.Contains("emergency");
        if (saysEmergency && saysCallingCode)
        {
            return PhoneIntent.UnsupportedSubcomponent;
        }

        if (saysEmergency)
        {
            return PhoneIntent.Emergency;
        }

        if (saysCallingCode)
        {
            return PhoneIntent.CallingCode;
        }

        if (saysAlternate && saysLandline && !saysMobile)
        {
            return PhoneIntent.UnsupportedSubcomponent;
        }

        if (saysAlternate && saysMobile)
        {
            return PhoneIntent.AlternateMobile;
        }

        if (saysAlternate)
        {
            return PhoneIntent.AlternateGeneric;
        }

        if (saysMobile)
        {
            return PhoneIntent.Mobile;
        }

        if (saysLandline)
        {
            return PhoneIntent.Landline;
        }

        return PhoneIntent.Generic;
    }

    private static bool ContainsPhrase(
        string normalizedMetadata,
        string normalizedPhrase) =>
        $" {normalizedMetadata} ".Contains(
            $" {normalizedPhrase} ",
            StringComparison.Ordinal);

    private static bool HasQualifiedSectionConflict(
        IEnumerable<MetadataSignal> signals,
        string canonicalFieldId)
    {
        HashSet<string> sectionTokens = signals
            .Where(signal =>
                signal.Source == MatchEvidenceSource.SectionHeading)
            .SelectMany(signal => ToTokens(signal.Normalized))
            .ToHashSet(StringComparer.Ordinal);
        if (sectionTokens.Count == 0 ||
            !IsSectionSensitivePassengerField(canonicalFieldId))
        {
            return false;
        }

        bool emergencySection = sectionTokens.Contains("emergency");
        bool historicalSection = sectionTokens.Overlaps(
            ["former", "old", "previous"]);
        bool alternateSection = sectionTokens.Overlaps(
            ["alternate", "alternative", "secondary"]);
        bool isEmergencyField =
            canonicalFieldId.StartsWith("emergency.", StringComparison.Ordinal);
        bool isHistoricalField =
            canonicalFieldId == "passport.old_number" ||
            canonicalFieldId.StartsWith(
                "personal.previous_",
                StringComparison.Ordinal);
        bool isAlternateField =
            canonicalFieldId.StartsWith(
                "contact.alternate_",
                StringComparison.Ordinal);
        return emergencySection && !isEmergencyField ||
            historicalSection && !isHistoricalField ||
            alternateSection && !isAlternateField;
    }

    private static bool IsSectionSensitivePassengerField(
        string canonicalFieldId) =>
        canonicalFieldId.StartsWith("address.", StringComparison.Ordinal) ||
        canonicalFieldId.StartsWith("contact.", StringComparison.Ordinal) ||
        canonicalFieldId.StartsWith("emergency.", StringComparison.Ordinal) ||
        canonicalFieldId.StartsWith("passport.", StringComparison.Ordinal) ||
        canonicalFieldId.StartsWith("personal.", StringComparison.Ordinal);

    private static void AddPhoneIntentEvidence(
        PhoneIntent intent,
        List<MetadataSignal> signals,
        HashSet<string> available,
        IDictionary<string, CandidateScore> candidates)
    {
        MetadataSignal signal = SelectPhoneSignal(signals);
        int genericScore = signal.Source switch
        {
            MatchEvidenceSource.AccessibleName => 86,
            MatchEvidenceSource.AutomationId => 82,
            MatchEvidenceSource.Placeholder => 80,
            MatchEvidenceSource.HelpText => 74,
            _ => 68,
        };
        int specificScore = Math.Min(94, genericScore + 6);

        switch (intent)
        {
            case PhoneIntent.Generic:
                AddRelatedCandidate(
                    "contact.mobile",
                    genericScore,
                    "GENERIC_TELEPHONE_RELATED");
                AddRelatedCandidate(
                    "contact.landline",
                    genericScore,
                    "GENERIC_TELEPHONE_RELATED");
                break;
            case PhoneIntent.Mobile:
                AddRelatedCandidate(
                    "contact.mobile",
                    specificScore,
                    "SPECIFIC_MOBILE_RELATED");
                break;
            case PhoneIntent.Landline:
                AddRelatedCandidate(
                    "contact.landline",
                    specificScore,
                    "SPECIFIC_LANDLINE_RELATED");
                break;
            case PhoneIntent.AlternateMobile:
                AddRelatedCandidate(
                    "contact.alternate_mobile",
                    specificScore,
                    "ALTERNATE_MOBILE_RELATED");
                break;
            case PhoneIntent.AlternateGeneric:
                AddRelatedCandidate(
                    "contact.alternate_mobile",
                    genericScore,
                    "ALTERNATE_CONTACT_RELATED");
                break;
            case PhoneIntent.CallingCode:
                AddRelatedCandidate(
                    "contact.country_calling_code",
                    specificScore,
                    "COUNTRY_CALLING_CODE_RELATED");
                break;
            case PhoneIntent.Emergency:
                AddRelatedCandidate(
                    "emergency.phone",
                    specificScore,
                    "EMERGENCY_PHONE_RELATED");
                break;
            case PhoneIntent.None:
            default:
                break;
        }

        void AddRelatedCandidate(
            string canonicalFieldId,
            int score,
            string reasonCode)
        {
            if (!available.Contains(canonicalFieldId))
            {
                return;
            }

            GetOrAddCandidate(canonicalFieldId, candidates)
                .AddEvidence(
                    new FieldMatchEvidence(
                        canonicalFieldId,
                        signal.Source,
                        score,
                        EvidenceRuleCode(reasonCode)),
                    reasonCode);
        }
    }

    private static MetadataSignal SelectPhoneSignal(
        List<MetadataSignal> signals)
    {
        return signals
            .Where(signal =>
                ToTokens(signal.Normalized).Overlaps(
                    ["calling", "cell", "cellular", "cellphone", "contact",
                     "dialing", "dialling", "landline", "mobile", "phone",
                     "tel", "telephone"]))
            .OrderByDescending(signal => signal.ExactScore)
            .FirstOrDefault()
            ?? signals.OrderByDescending(signal => signal.ExactScore).First();
    }

    private RankedFieldCandidate ToRankedCandidate(
        CandidateScore candidate)
    {
        string displayName = _catalog.TryGetDefinition(
            candidate.CanonicalFieldId,
            out CanonicalFieldDefinition? definition)
            && definition is not null
                ? definition.DisplayName
                : candidate.CanonicalFieldId;
        return new RankedFieldCandidate(
            candidate.CanonicalFieldId,
            displayName,
            candidate.FinalScore,
            ConfidenceFor(candidate.FinalScore),
            candidate.PrimaryReasonCode,
            Array.AsReadOnly(OrderEvidence(candidate.Evidence)));
    }

    private static FieldCandidateConfidence ConfidenceFor(int score) =>
        score switch
        {
            >= 90 => FieldCandidateConfidence.High,
            >= 75 => FieldCandidateConfidence.Medium,
            _ => FieldCandidateConfidence.Low,
        };

    private bool HasBlockingTargetToken(
        string canonicalFieldId,
        string normalizedMetadata)
    {
        if (!_catalog.TryGetDefinition(
            canonicalFieldId,
            out CanonicalFieldDefinition? definition)
            || definition is null)
        {
            return false;
        }

        string paddedMetadata = $" {normalizedMetadata} ";
        return definition.BlockingTargetTokens.Any(token =>
            paddedMetadata.Contains($" {token} ", StringComparison.Ordinal));
    }

    private static bool TryMaterializeAvailableFields(
        IEnumerable<string> source,
        out HashSet<string> available)
    {
        string[] materialized = source
            .Where(fieldId => !string.IsNullOrWhiteSpace(fieldId))
            .Take(MaximumAvailableFields + 1)
            .ToArray();
        if (materialized.Length > MaximumAvailableFields
            || materialized.Any(fieldId => fieldId.Length > 96))
        {
            available = new HashSet<string>(StringComparer.Ordinal);
            return false;
        }

        available = materialized.ToHashSet(StringComparer.Ordinal);
        return true;
    }

    private static CandidateScore GetOrAddCandidate(
        string canonicalFieldId,
        IDictionary<string, CandidateScore> candidates)
    {
        if (!candidates.TryGetValue(
            canonicalFieldId,
            out CandidateScore? candidate))
        {
            candidate = new CandidateScore(canonicalFieldId);
            candidates.Add(canonicalFieldId, candidate);
        }

        return candidate;
    }

    private static string CombinedMetadata(
        IEnumerable<MetadataSignal> signals) =>
        string.Join(
            ' ',
            signals
                .Select(signal => signal.Normalized)
                .Where(value => value.Length > 0));

    private static HashSet<string> ToTokens(string normalized) =>
        normalized
            .Split(
                ' ',
                StringSplitOptions.RemoveEmptyEntries
                    | StringSplitOptions.TrimEntries)
            .ToHashSet(StringComparer.Ordinal);

    private static string EvidenceSourceCode(MatchEvidenceSource source) =>
        source switch
        {
            MatchEvidenceSource.AccessibleName => "accessible-name",
            MatchEvidenceSource.AutomationId => "automation-id",
            MatchEvidenceSource.HelpText => "help-text",
            MatchEvidenceSource.Placeholder => "placeholder",
            MatchEvidenceSource.SectionHeading => "section-heading",
            MatchEvidenceSource.ContextualMetadata => "contextual-metadata",
            MatchEvidenceSource.SavedMapping => "saved-mapping",
            _ => "metadata",
        };

    private static string EvidenceRuleCode(string reasonCode) =>
        reasonCode.ToLowerInvariant().Replace('_', '-');

    private static FieldMatchEvidence[] OrderEvidence(
        IEnumerable<FieldMatchEvidence> evidence) =>
        evidence
            .OrderByDescending(item => item.Score)
            .ThenBy(item => item.CanonicalFieldId, StringComparer.Ordinal)
            .ThenBy(item => item.Source)
            .ThenBy(item => item.Rule, StringComparer.Ordinal)
            .ToArray();

    private static bool LengthExceeds(string? value, int maximum) =>
        value?.Length > maximum;

    private static FieldMatchResult Blocked(string reasonCode) =>
        new(
            FieldMatchStatus.Blocked,
            null,
            0,
            Array.Empty<FieldMatchEvidence>(),
            reasonCode);

    private static FieldMatchResult Unknown(
        string reasonCode,
        IReadOnlyList<FieldMatchEvidence> evidence) =>
        new(
            FieldMatchStatus.Unknown,
            null,
            0,
            evidence,
            reasonCode);

    private static FieldCandidateRankingResult BlockedRanking(
        string reasonCode) =>
        new(
            FieldCandidateRankingStatus.Blocked,
            Array.Empty<RankedFieldCandidate>(),
            reasonCode);

    private static FieldCandidateRankingResult NoRelatedCandidates(
        string reasonCode) =>
        new(
            FieldCandidateRankingStatus.NoRelatedCandidates,
            Array.Empty<RankedFieldCandidate>(),
            reasonCode);

    private sealed record MetadataSignal(
        string Normalized,
        MatchEvidenceSource Source,
        int ExactScore,
        int ContextualScore,
        string ExactRule,
        string ExactReasonCode);

    private enum PhoneIntent
    {
        None,
        Generic,
        Mobile,
        Landline,
        AlternateMobile,
        AlternateGeneric,
        CallingCode,
        Emergency,
        UnsupportedSubcomponent,
    }

    private sealed class CandidateScore
    {
        private readonly HashSet<MatchEvidenceSource> _sources = [];
        private readonly List<FieldMatchEvidence> _evidence = [];
        private int _primaryReasonScore = -1;

        public CandidateScore(string canonicalFieldId)
        {
            CanonicalFieldId = canonicalFieldId;
        }

        public string CanonicalFieldId { get; }

        public int FinalScore { get; private set; }

        public string PrimaryReasonCode { get; private set; } =
            "RELATED_METADATA";

        public IReadOnlyList<FieldMatchEvidence> Evidence => _evidence;

        public void AddEvidence(
            FieldMatchEvidence evidence,
            string reasonCode)
        {
            if (!_evidence.Contains(evidence))
            {
                _evidence.Add(evidence);
                _sources.Add(evidence.Source);
            }

            if (evidence.Score > _primaryReasonScore
                || evidence.Score == _primaryReasonScore
                && string.CompareOrdinal(
                    reasonCode,
                    PrimaryReasonCode) < 0)
            {
                PrimaryReasonCode = reasonCode;
                _primaryReasonScore = evidence.Score;
            }
        }

        public CandidateScore WithFinalScore()
        {
            int maximum = _evidence.Max(evidence => evidence.Score);
            int consistencyBonus =
                Math.Min(4, Math.Max(0, _sources.Count - 1) * 2);
            FinalScore = Math.Min(99, maximum + consistencyBonus);
            return this;
        }
    }
}

internal static class CandidateDictionaryExtensions
{
    public static int RemoveWhere<TKey, TValue>(
        this IDictionary<TKey, TValue> dictionary,
        Func<KeyValuePair<TKey, TValue>, bool> predicate)
        where TKey : notnull
    {
        TKey[] keys = dictionary
            .Where(predicate)
            .Select(pair => pair.Key)
            .ToArray();
        foreach (TKey key in keys)
        {
            dictionary.Remove(key);
        }

        return keys.Length;
    }
}
