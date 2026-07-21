using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using SmartCopyPaste.App.Interop;
using SmartCopyPaste.App.Models;
using SmartCopyPaste.Core.Configuration;

namespace SmartCopyPaste.App.Services;

internal sealed class ProtectedSettingsStore
{
    private const string SettingsFileName = "settings.json";
    private const long MaximumSettingsBytes = 1_048_576;
    private readonly JsonSerializerOptions jsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase) },
    };

    internal ProtectedSettingsStore(string? dataDirectory = null)
    {
        DataDirectory = dataDirectory ??
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SmartCopyPaste");
        SettingsPath = Path.Combine(DataDirectory, SettingsFileName);
    }

    internal string DataDirectory { get; }

    internal string SettingsPath { get; }

    internal SettingsLoadResult Load()
    {
        try
        {
            if (!File.Exists(SettingsPath))
            {
                PersistedAppSettings created = CreateFreshSettings();
                Save(created);
                return new SettingsLoadResult(created, null);
            }

            if (new FileInfo(SettingsPath).Length > MaximumSettingsBytes)
            {
                throw new InvalidDataException("The settings file exceeds its size limit.");
            }

            string json = File.ReadAllText(SettingsPath);
            PersistedAppSettings? settings = JsonSerializer.Deserialize<PersistedAppSettings>(json, jsonOptions);
            if (settings is null || settings.SchemaVersion != 1)
            {
                return new SettingsLoadResult(
                    CreateFreshSettings(),
                    "Settings were not loaded because their version is unsupported.");
            }

            EnsureDefaults(settings);
            SettingsValidationResult validation =
                SettingsValidator.Validate(HotkeySettingsAdapter.ToCoreSettings(settings));
            if (!validation.IsValid)
            {
                throw new InvalidDataException(validation.Issues[0].Message);
            }

            _ = GetUserSecret(settings);
            return new SettingsLoadResult(settings, null);
        }
        catch (Exception exception) when (
            exception is IOException or
            UnauthorizedAccessException or
            JsonException or
            CryptographicException or
            FormatException or
            InvalidDataException)
        {
            return new SettingsLoadResult(
                CreateFreshSettings(),
                "Settings could not be loaded. Safe defaults are active for this session.");
        }
    }

    internal void Save(PersistedAppSettings settings)
    {
        ArgumentNullException.ThrowIfNull(settings);
        Directory.CreateDirectory(DataDirectory);

        string temporaryPath = SettingsPath + ".tmp";
        PersistedAppSettings persistable = CreatePersistableSnapshot(settings);
        EnsureDefaults(persistable);
        SettingsValidationResult validation =
            SettingsValidator.Validate(HotkeySettingsAdapter.ToCoreSettings(persistable));
        if (!validation.IsValid)
        {
            throw new InvalidDataException(validation.Issues[0].Message);
        }

        string json = JsonSerializer.Serialize(persistable, jsonOptions);
        using (var stream = new FileStream(
            temporaryPath,
            FileMode.Create,
            FileAccess.Write,
            FileShare.None))
        using (var writer = new StreamWriter(stream, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false)))
        {
            writer.Write(json);
            writer.Flush();
            stream.Flush(flushToDisk: true);
        }

        if (File.Exists(SettingsPath))
        {
            File.Replace(temporaryPath, SettingsPath, destinationBackupFileName: null, ignoreMetadataErrors: true);
        }
        else
        {
            File.Move(temporaryPath, SettingsPath);
        }
    }

    internal static byte[] GetUserSecret(PersistedAppSettings settings)
    {
        ArgumentNullException.ThrowIfNull(settings);
        if (string.IsNullOrWhiteSpace(settings.ProtectedUserSecret))
        {
            byte[] secret = RandomNumberGenerator.GetBytes(32);
            settings.ProtectedUserSecret = Convert.ToBase64String(NativeMethods.ProtectCurrentUser(secret));
            return secret;
        }

        byte[] protectedSecret = Convert.FromBase64String(settings.ProtectedUserSecret);
        byte[] unprotected = NativeMethods.UnprotectCurrentUser(protectedSecret);
        if (unprotected.Length != 32)
        {
            throw new CryptographicException("The protected user secret has an invalid length.");
        }

        return unprotected;
    }

    private static PersistedAppSettings CreateFreshSettings()
    {
        PersistedAppSettings settings = new();
        byte[] temporarySecret = GetUserSecret(settings);
        CryptographicOperations.ZeroMemory(temporarySecret);
        return settings;
    }

    private static void EnsureDefaults(PersistedAppSettings settings)
    {
        settings.Hotkeys ??= new Dictionary<HotkeyCommand, HotkeySetting>();
        settings.CustomHeaderAliases ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        settings.HeaderTemplates ??= [];

        Dictionary<HotkeyCommand, HotkeySetting> defaults = PersistedAppSettings.CreateDefaultHotkeys();
        foreach ((HotkeyCommand command, HotkeySetting gesture) in defaults)
        {
            settings.Hotkeys.TryAdd(command, gesture);
        }

        if (settings.HeaderTemplates.Count > 256 ||
            settings.HeaderTemplates.OfType<HeaderTemplateRecord>().Any(
                static template => template.Columns is null || template.Columns.Count > 128))
        {
            throw new InvalidDataException("The settings contain too many header profiles or columns.");
        }

        settings.HeaderTemplates = settings.HeaderTemplates
            .OfType<HeaderTemplateRecord>()
            .Where(static template => !template.SessionOnly)
            .ToList();
        var templateIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var sourceIdentities = new HashSet<string>(StringComparer.Ordinal);
        foreach (HeaderTemplateRecord template in settings.HeaderTemplates)
        {
            if (template.SchemaVersion != 1 ||
                string.IsNullOrWhiteSpace(template.DisplayName) ||
                template.DisplayName.Length > 160 ||
                template.ColumnCount != template.Columns.Count ||
                !templateIds.Add(template.TemplateId) ||
                !sourceIdentities.Add($"{template.WorkbookIdentity}\n{template.WorksheetIdentity}"))
            {
                throw new InvalidDataException("A stored header profile is invalid or duplicated.");
            }

            try
            {
                _ = HeaderTemplateAdapter.ToCore(template);
            }
            catch (Exception exception) when (
                exception is ArgumentException or InvalidDataException)
            {
                throw new InvalidDataException("A stored header profile failed validation.", exception);
            }
        }

        if (settings.ActiveFallbackTemplateId is not null &&
            !settings.HeaderTemplates.Any(template => string.Equals(
                template.TemplateId,
                settings.ActiveFallbackTemplateId,
                StringComparison.Ordinal)))
        {
            settings.ActiveFallbackTemplateId = null;
        }

        settings.CustomHeaderAliases =
            new Dictionary<string, string>(
                settings.CustomHeaderAliases,
                StringComparer.OrdinalIgnoreCase);
        settings.InactivityMinutes = Math.Clamp(settings.InactivityMinutes, 1, 480);
        if (string.IsNullOrWhiteSpace(settings.ActiveFallbackTemplateId))
        {
            settings.ActiveFallbackTemplateId = null;
        }
    }

    private static PersistedAppSettings CreatePersistableSnapshot(PersistedAppSettings source)
    {
        List<HeaderTemplateRecord> templates = source.HeaderTemplates
            .Where(static template => !template.SessionOnly)
            .Select(CloneTemplate)
            .ToList();
        string? activeFallbackTemplateId = templates.Any(template =>
            string.Equals(
                template.TemplateId,
                source.ActiveFallbackTemplateId,
                StringComparison.Ordinal))
            ? source.ActiveFallbackTemplateId
            : null;

        return new PersistedAppSettings
        {
            SchemaVersion = source.SchemaVersion,
            ProtectedUserSecret = source.ProtectedUserSecret,
            StartWithWindows = source.StartWithWindows,
            InactivityMinutes = source.InactivityMinutes,
            ActiveFallbackTemplateId = activeFallbackTemplateId,
            Hotkeys = HotkeySettingsAdapter.Clone(source.Hotkeys),
            CustomHeaderAliases = new Dictionary<string, string>(
                source.CustomHeaderAliases,
                StringComparer.OrdinalIgnoreCase),
            HeaderTemplates = templates,
        };
    }

    private static HeaderTemplateRecord CloneTemplate(HeaderTemplateRecord source) =>
        new()
        {
            SchemaVersion = source.SchemaVersion,
            TemplateId = source.TemplateId,
            DisplayName = source.DisplayName,
            WorkbookIdentity = source.WorkbookIdentity,
            WorksheetIdentity = source.WorksheetIdentity,
            HeaderRow = source.HeaderRow,
            FirstColumn = source.FirstColumn,
            ColumnCount = source.ColumnCount,
            HeaderFingerprint = source.HeaderFingerprint,
            SessionOnly = false,
            Columns = source.Columns
                .Select(static column => new HeaderColumnRecord
                {
                    Offset = column.Offset,
                    OriginalHeader = column.OriginalHeader,
                    CanonicalFieldId = column.CanonicalFieldId,
                    Ignored = column.Ignored,
                })
                .ToList(),
        };
}
