using System.Security.Cryptography;
using System.Text;

namespace SmartCopyPaste.App.Services;

internal static class WorkbookIdentityService
{
    internal static string ComputeWorkbookIdentity(byte[] userSecret, string workbookFullName)
    {
        ArgumentNullException.ThrowIfNull(userSecret);
        ArgumentException.ThrowIfNullOrWhiteSpace(workbookFullName);
        string normalized = Path.GetFullPath(workbookFullName)
            .Trim()
            .ToUpperInvariant();
        return Compute(userSecret, $"workbook-v1\n{normalized}");
    }

    internal static string ComputeWorksheetIdentity(
        byte[] userSecret,
        string workbookIdentity,
        string worksheetCodeName)
    {
        ArgumentNullException.ThrowIfNull(userSecret);
        ArgumentException.ThrowIfNullOrWhiteSpace(workbookIdentity);
        ArgumentException.ThrowIfNullOrWhiteSpace(worksheetCodeName);
        return Compute(
            userSecret,
            $"worksheet-v1\n{workbookIdentity}\n{worksheetCodeName.Trim().ToUpperInvariant()}");
    }

    private static string Compute(byte[] key, string value)
    {
        byte[] digest = HMACSHA256.HashData(key, Encoding.UTF8.GetBytes(value));
        return Convert.ToHexString(digest);
    }
}
