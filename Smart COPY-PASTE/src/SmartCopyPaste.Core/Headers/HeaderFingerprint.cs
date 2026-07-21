using System.Security.Cryptography;
using System.Text;
using SmartCopyPaste.Core.Normalization;

namespace SmartCopyPaste.Core.Headers;

public static class HeaderFingerprint
{
    public const int Version = 1;

    public static string Compute(IEnumerable<string?> headers)
    {
        ArgumentNullException.ThrowIfNull(headers);
        string[] materialized = headers
            .Select(header => DeterministicTextNormalizer.Normalize(header))
            .ToArray();

        var canonical = new StringBuilder();
        canonical.Append("header-fingerprint-v");
        canonical.Append(Version);
        canonical.Append('\n');
        for (int index = 0; index < materialized.Length; index++)
        {
            string header = materialized[index];
            canonical.Append(index);
            canonical.Append(':');
            canonical.Append(header.Length);
            canonical.Append(':');
            canonical.Append(header);
            canonical.Append('\n');
        }

        byte[] digest = SHA256.HashData(Encoding.UTF8.GetBytes(canonical.ToString()));
        return Convert.ToHexString(digest);
    }
}
