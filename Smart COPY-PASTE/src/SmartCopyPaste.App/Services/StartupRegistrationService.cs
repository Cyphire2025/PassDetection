using Microsoft.Win32;

namespace SmartCopyPaste.App.Services;

internal static class StartupRegistrationService
{
    private const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "SmartCopyPaste";

    internal static bool TrySetEnabled(bool enabled)
    {
        try
        {
            using RegistryKey? runKey = Registry.CurrentUser.OpenSubKey(RunKeyPath, writable: true);
            if (runKey is null)
            {
                return false;
            }

            if (!enabled)
            {
                runKey.DeleteValue(ValueName, throwOnMissingValue: false);
                return true;
            }

            string? executablePath = Environment.ProcessPath;
            if (string.IsNullOrWhiteSpace(executablePath))
            {
                return false;
            }

            runKey.SetValue(
                ValueName,
                $"\"{executablePath}\" --startup",
                RegistryValueKind.String);
            return true;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }
        catch (IOException)
        {
            return false;
        }
    }
}
