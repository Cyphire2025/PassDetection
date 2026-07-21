using System.Security.Cryptography;
using System.Text;
using SmartCopyPaste.App.Models;
using SmartCopyPaste.Core.Normalization;

namespace SmartCopyPaste.App.Services;

/// <summary>
/// Remembers a user-confirmed target-field choice for this process only. Keys are
/// one-way hashes of bounded, normalized accessibility metadata; raw page labels
/// are never persisted or logged.
/// </summary>
internal sealed class SessionTargetMappingStore
{
    private const int MaximumMappings = 256;
    private readonly Dictionary<string, string> mappings = new(StringComparer.Ordinal);
    private readonly Queue<string> insertionOrder = new();

    internal bool TryGet(FocusedFieldSnapshot field, out string? canonicalFieldId)
    {
        ArgumentNullException.ThrowIfNull(field);
        string? signature = CreateSignature(field);
        if (signature is not null &&
            mappings.TryGetValue(signature, out string? stored))
        {
            canonicalFieldId = stored;
            return true;
        }

        canonicalFieldId = null;
        return false;
    }

    internal bool Remember(FocusedFieldSnapshot field, string canonicalFieldId)
    {
        ArgumentNullException.ThrowIfNull(field);
        ArgumentException.ThrowIfNullOrWhiteSpace(canonicalFieldId);
        if (canonicalFieldId.Length > 96)
        {
            return false;
        }

        string? signature = CreateSignature(field);
        if (signature is null)
        {
            return false;
        }

        if (!mappings.ContainsKey(signature))
        {
            while (mappings.Count >= MaximumMappings && insertionOrder.Count > 0)
            {
                _ = mappings.Remove(insertionOrder.Dequeue());
            }

            insertionOrder.Enqueue(signature);
        }

        mappings[signature] = canonicalFieldId;
        return true;
    }

    internal void Clear()
    {
        mappings.Clear();
        insertionOrder.Clear();
    }

    internal static string? CreateSignature(FocusedFieldSnapshot field)
    {
        ArgumentNullException.ThrowIfNull(field);
        string accessibleName = DeterministicTextNormalizer.Normalize(field.AccessibleName);
        string automationId = DeterministicTextNormalizer.Normalize(field.AutomationId);
        string helpText = DeterministicTextNormalizer.Normalize(field.HelpText);
        string placeholder = DeterministicTextNormalizer.Normalize(field.Placeholder);
        string runtimeIdentity = field.RuntimeIdentity.Trim();
        if (runtimeIdentity.Length == 0 ||
            accessibleName.Length == 0 &&
            automationId.Length == 0 &&
            helpText.Length == 0 &&
            placeholder.Length == 0)
        {
            return null;
        }

        string material = string.Join(
            '\n',
            field.ProcessName.Trim().ToLowerInvariant(),
            field.ProcessId.ToString(System.Globalization.CultureInfo.InvariantCulture),
            field.ForegroundWindow.ToInt64().ToString(
                "X",
                System.Globalization.CultureInfo.InvariantCulture),
            runtimeIdentity,
            DeterministicTextNormalizer.Normalize(field.ControlType),
            accessibleName,
            automationId,
            helpText,
            DeterministicTextNormalizer.Normalize(field.ClassName),
            placeholder,
            DeterministicTextNormalizer.Normalize(field.SectionHeading),
            DeterministicTextNormalizer.Normalize(field.InputType),
            DeterministicTextNormalizer.Normalize(field.FormatHint));
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(material)));
    }
}
