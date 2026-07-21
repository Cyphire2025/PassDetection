using SmartCopyPaste.Core.Catalog;
using SmartCopyPaste.Core.Headers;
using System.Text.Json;

namespace SmartCopyPaste.Core.Tests;

public sealed class HeaderTemplateTests
{
    [Fact]
    public void Fingerprint_IsNormalizedOrderSensitiveAndDeterministic()
    {
        string first = HeaderFingerprint.Compute(
            new[] { "Surname", "PassportNumber" });
        string equivalent = HeaderFingerprint.Compute(
            new[] { " surname ", "passport_number" });
        string reordered = HeaderFingerprint.Compute(
            new[] { "Passport Number", "Surname" });

        Assert.Equal(first, equivalent);
        Assert.NotEqual(first, reordered);
        Assert.Equal(first, HeaderFingerprint.Compute(
            new[] { "Surname", "PassportNumber" }));
    }

    [Fact]
    public void Factory_CreatesOpaqueWorkbookScopedTemplate()
    {
        HeaderTemplateCreateResult result = HeaderTemplateFactory.Create(
            "workbook-opaque-key",
            "sheet-opaque-key",
            headerRow: 4,
            firstSourceColumn: 2,
            new[] { "Surname", "Passport No.", "Email" },
            CanonicalFieldCatalog.Default,
            createdAt: DateTimeOffset.UnixEpoch);

        Assert.True(result.Success);
        HeaderTemplate template = Assert.IsType<HeaderTemplate>(result.Template);
        Assert.Equal("workbook-opaque-key", template.WorkbookKey);
        Assert.Equal("sheet-opaque-key", template.SheetKey);
        Assert.Equal(4, template.HeaderRow);
        Assert.Equal(2, template.FirstSourceColumn);
        Assert.Equal(
            new[] { 2, 3, 4 },
            template.Columns.Select(column => column.SourceColumn));
        Assert.Equal(
            new[] { "personal.surname", "passport.number", "contact.email" },
            template.Columns.Select(column => column.FieldId));
        Assert.All(
            template.Columns,
            column => Assert.Equal(HeaderMappingKind.Automatic, column.MappingKind));
        Assert.True(template.MatchesHeaders(
            new[] { "surname", "PassportNo", "EMAIL" }));
        Assert.False(template.MatchesHeaders(
            new[] { "Email", "Passport No", "Surname" }));
    }

    [Fact]
    public void Factory_RequiresExplicitUnknownMappingOrIgnore()
    {
        HeaderTemplateCreateResult unresolved = HeaderTemplateFactory.Create(
            "workbook",
            "sheet",
            1,
            1,
            new[] { "Surname", "Internal Reference", "Notes" },
            CanonicalFieldCatalog.Default);

        Assert.False(unresolved.Success);
        Assert.Equal(2, unresolved.Issues.Count(issue => issue.Code == "HEADER_UNKNOWN"));

        string customId = HeaderTemplateFactory.CreateCustomFieldId("Internal Reference");
        var overrides = new Dictionary<int, HeaderMappingOverride>
        {
            [1] = new(HeaderMappingKind.Custom, customId),
            [2] = new(HeaderMappingKind.Ignored, null),
        };
        HeaderTemplateCreateResult resolved = HeaderTemplateFactory.Create(
            "workbook",
            "sheet",
            1,
            1,
            new[] { "Surname", "Internal Reference", "Notes" },
            CanonicalFieldCatalog.Default,
            overrides);

        Assert.True(resolved.Success);
        HeaderTemplate template = Assert.IsType<HeaderTemplate>(resolved.Template);
        Assert.Equal(customId, template.Columns[1].FieldId);
        Assert.Equal(HeaderMappingKind.Custom, template.Columns[1].MappingKind);
        Assert.Equal(HeaderMappingKind.Ignored, template.Columns[2].MappingKind);
        Assert.Null(template.Columns[2].FieldId);
    }

    [Fact]
    public void Factory_RejectsDuplicateCanonicalMappings()
    {
        HeaderTemplateCreateResult result = HeaderTemplateFactory.Create(
            "workbook",
            "sheet",
            1,
            1,
            new[] { "Passport Number", "Passport No." },
            CanonicalFieldCatalog.Default);

        Assert.False(result.Success);
        Assert.Contains(
            result.Issues,
            issue => issue.Code == "DUPLICATE_FIELD_MAPPING");
    }

    [Fact]
    public void Factory_RejectsUnknownManualCanonicalId()
    {
        var overrides = new Dictionary<int, HeaderMappingOverride>
        {
            [0] = new(HeaderMappingKind.Manual, "does.not_exist"),
        };

        HeaderTemplateCreateResult result = HeaderTemplateFactory.Create(
            "workbook",
            "sheet",
            1,
            1,
            new[] { "Mystery" },
            CanonicalFieldCatalog.Default,
            overrides);

        Assert.False(result.Success);
        Assert.Contains(
            result.Issues,
            issue => issue.Code == "MAPPING_FIELD_UNKNOWN");
    }

    [Fact]
    public void Factory_RejectsOverrideOutsideSelectedHeaderRange()
    {
        var overrides = new Dictionary<int, HeaderMappingOverride>
        {
            [4] = new(HeaderMappingKind.Ignored, null),
        };

        HeaderTemplateCreateResult result = HeaderTemplateFactory.Create(
            "workbook",
            "sheet",
            1,
            1,
            new[] { "Surname" },
            CanonicalFieldCatalog.Default,
            overrides);

        Assert.False(result.Success);
        Assert.Contains(
            result.Issues,
            issue => issue.Code == "HEADER_OVERRIDE_OUT_OF_RANGE");
    }

    [Fact]
    public void CustomFieldId_TransliteratesAccentedLatinHeaderToValidAscii()
    {
        string customId = HeaderTemplateFactory.CreateCustomFieldId("Prénom");
        var overrides = new Dictionary<int, HeaderMappingOverride>
        {
            [0] = new(HeaderMappingKind.Custom, customId),
        };

        HeaderTemplateCreateResult result = HeaderTemplateFactory.Create(
            "workbook",
            "sheet",
            1,
            1,
            new[] { "Prénom" },
            CanonicalFieldCatalog.Default,
            overrides);

        Assert.StartsWith("custom.prenom.", customId, StringComparison.Ordinal);
        Assert.True(result.Success);
        Assert.Equal(customId, result.Template?.Columns[0].FieldId);
    }

    [Fact]
    public void CustomFieldId_UsesHashBackedAsciiFallbackForNonLatinHeader()
    {
        string first = HeaderTemplateFactory.CreateCustomFieldId("नाम");
        string repeated = HeaderTemplateFactory.CreateCustomFieldId("नाम");
        string vowelVariant = HeaderTemplateFactory.CreateCustomFieldId("निम");
        string different = HeaderTemplateFactory.CreateCustomFieldId("姓氏");
        var overrides = new Dictionary<int, HeaderMappingOverride>
        {
            [0] = new(HeaderMappingKind.Custom, first),
        };

        HeaderTemplateCreateResult result = HeaderTemplateFactory.Create(
            "workbook",
            "sheet",
            1,
            1,
            new[] { "नाम" },
            CanonicalFieldCatalog.Default,
            overrides);

        Assert.StartsWith("custom.field.", first, StringComparison.Ordinal);
        Assert.Equal(first, repeated);
        Assert.NotEqual(first, vowelVariant);
        Assert.NotEqual(first, different);
        Assert.Matches("^custom\\.[a-z0-9_]+\\.[a-f0-9]{8}$", first);
        Assert.True(result.Success);
        Assert.Equal(first, result.Template?.Columns[0].FieldId);
    }

    [Fact]
    public void Template_RejectsTamperedFingerprint()
    {
        HeaderTemplateCreateResult result = HeaderTemplateFactory.Create(
            "workbook",
            "sheet",
            1,
            1,
            new[] { "Surname" },
            CanonicalFieldCatalog.Default);
        HeaderTemplate original = Assert.IsType<HeaderTemplate>(result.Template);

        Assert.Throws<ArgumentException>(() => new HeaderTemplate(
            original.SchemaVersion,
            original.TemplateId,
            original.WorkbookKey,
            original.SheetKey,
            original.HeaderRow,
            original.FirstSourceColumn,
            original.Columns,
            new string('A', 64),
            original.CatalogVersion,
            original.CreatedAt));
    }

    [Fact]
    public void VersionedTemplate_SerializesAndRevalidatesOnRoundTrip()
    {
        HeaderTemplateCreateResult result = HeaderTemplateFactory.Create(
            "workbook-key",
            "sheet-key",
            3,
            2,
            new[] { "Surname", "Passport Number" },
            CanonicalFieldCatalog.Default,
            createdAt: DateTimeOffset.UnixEpoch);
        HeaderTemplate original = Assert.IsType<HeaderTemplate>(result.Template);

        string json = JsonSerializer.Serialize(original);
        HeaderTemplate restored = Assert.IsType<HeaderTemplate>(
            JsonSerializer.Deserialize<HeaderTemplate>(json));

        Assert.Equal(original.SchemaVersion, restored.SchemaVersion);
        Assert.Equal(original.TemplateId, restored.TemplateId);
        Assert.Equal(original.WorkbookKey, restored.WorkbookKey);
        Assert.Equal(original.OrderedHeaderFingerprint, restored.OrderedHeaderFingerprint);
        Assert.Equal(original.Columns, restored.Columns);
    }
}
