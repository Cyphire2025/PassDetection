using System.Collections.ObjectModel;
using SmartCopyPaste.Core.Contracts;
using SmartCopyPaste.Core.Security;

namespace SmartCopyPaste.Core.Diagnostics;

public enum DiagnosticSeverity
{
    Information,
    Warning,
    Error,
}

public sealed record SanitizedDiagnosticSnapshot(
    string ApplicationVersion,
    int CanonicalCatalogVersion,
    int SettingsSchemaVersion,
    int HeaderTemplateCount,
    int ActivePassengerCount,
    bool IsPaused,
    string HotkeyRegistrationStatus,
    string? LastErrorCode);

public sealed record SanitizedDiagnosticEvent(
    DateTimeOffset Timestamp,
    string Code,
    string Component,
    DiagnosticSeverity Severity,
    IReadOnlyDictionary<string, string> Metadata)
{
    public static SanitizedDiagnosticEvent Create(
        DateTimeOffset timestamp,
        string code,
        string component,
        DiagnosticSeverity severity,
        IReadOnlyDictionary<string, string>? metadata = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(code);
        ArgumentException.ThrowIfNullOrWhiteSpace(component);
        return new SanitizedDiagnosticEvent(
            timestamp,
            code,
            component,
            severity,
            metadata is null
                ? new ReadOnlyDictionary<string, string>(
                    new Dictionary<string, string>(StringComparer.Ordinal))
                : DiagnosticRedactor.RedactMetadata(metadata));
    }
}

public sealed record SanitizedDiagnosticReport(
    int SchemaVersion,
    DateTimeOffset GeneratedAt,
    SanitizedDiagnosticSnapshot Snapshot,
    IReadOnlyList<SanitizedDiagnosticEvent> Events)
{
    public static SanitizedDiagnosticReport Create(
        SanitizedDiagnosticSnapshot snapshot,
        IEnumerable<SanitizedDiagnosticEvent>? events = null)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        SanitizedDiagnosticEvent[] boundedEvents = (events ?? [])
            .TakeLast(100)
            .ToArray();
        return new SanitizedDiagnosticReport(
            ContractVersions.Diagnostics,
            DateTimeOffset.UtcNow,
            snapshot,
            Array.AsReadOnly(boundedEvents));
    }
}
