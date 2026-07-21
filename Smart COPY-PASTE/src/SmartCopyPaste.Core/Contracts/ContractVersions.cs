namespace SmartCopyPaste.Core.Contracts;

public static class ContractVersions
{
    public const int CanonicalCatalog = 1;
    public const int HeaderTemplate = 1;
    public const int Settings = 1;
    public const int Diagnostics = 1;
}

public sealed record VersionedMessage<TPayload>(
    int SchemaVersion,
    string MessageType,
    Guid CorrelationId,
    TPayload Payload)
    where TPayload : notnull;
