using SmartCopyPaste.Core.Catalog;
using SmartCopyPaste.Core.Headers;
using SmartCopyPaste.Core.Parsing;
using SmartCopyPaste.Core.Session;

namespace SmartCopyPaste.Core.Tests;

public sealed class TabularDataParserTests
{
    private readonly TabularDataParser _parser = new();

    [Fact]
    public void Parse_PreservesEmptyAndTrailingCells()
    {
        TabularParseResult result = _parser.Parse("a\t\tc\r\n1\t2\t");

        Assert.True(result.Success);
        Assert.Equal(2, result.Rows.Count);
        Assert.Equal(new[] { "a", "", "c" }, result.Rows[0]);
        Assert.Equal(new[] { "1", "2", "" }, result.Rows[1]);
    }

    [Fact]
    public void Parse_HandlesQuotedTabsNewlinesAndEscapedQuotes()
    {
        TabularParseResult result = _parser.Parse(
            "\"Surname\"\t\"Note\"\r\n\"Sharma\"\t\"Line 1\tTabbed\r\nLine \"\"2\"\"\"");

        Assert.True(result.Success);
        Assert.Equal("Line 1\tTabbed\nLine \"2\"", result.Rows[1][1]);
    }

    [Fact]
    public void Parse_RejectsMalformedQuotedCell()
    {
        TabularParseResult result = _parser.Parse("\"not closed");

        Assert.False(result.Success);
        Assert.Contains(result.Issues, issue => issue.Code == "MALFORMED_TSV");
    }

    [Fact]
    public void Parse_EnforcesConfiguredBounds()
    {
        var parser = new TabularDataParser(
            options: new TabularDataParserOptions(
                MaxInputCharacters: 20,
                MaxRows: 2,
                MaxColumns: 2,
                MaxCellCharacters: 4,
                MaxTotalCells: 4));

        Assert.Contains(
            parser.Parse("12345").Issues,
            issue => issue.Code == "CELL_TOO_LARGE");
        Assert.Contains(
            parser.Parse("a\tb\tc").Issues,
            issue => issue.Code == "TOO_MANY_COLUMNS");
        Assert.Contains(
            parser.Parse("a\nb\nc").Issues,
            issue => issue.Code == "TOO_MANY_ROWS");
        Assert.Contains(
            parser.Parse(new string('a', 21)).Issues,
            issue => issue.Code == "INPUT_TOO_LARGE");
    }

    [Fact]
    public void ParseRows_UsesSavedHeadersWithoutRequiringHeaderAgain()
    {
        HeaderTemplate template = CreateTemplate(
            "Surname",
            "Given Name",
            "Passport Number",
            "Mobile Number");

        PassengerParseResult result = _parser.ParseRows(
            "Sharma\tRahul\t0012345\t09876543210",
            template);

        Assert.True(result.Success);
        PassengerProfile profile = Assert.Single(result.Profiles);
        Assert.Equal("Rahul Sharma", profile.DisplayName);
        Assert.Equal("Sharma", profile.Fields["personal.surname"]);
        Assert.Equal("Rahul", profile.Fields["personal.given_name"]);
        Assert.Equal("0012345", profile.Fields["passport.number"]);
        Assert.Equal("09876543210", profile.Fields["contact.mobile"]);
        Assert.Equal(template.TemplateId, profile.HeaderTemplateId);
    }

    [Fact]
    public void ParseRows_CreatesOrderedMultiPassengerCollection()
    {
        HeaderTemplate template = CreateTemplate(
            "Surname",
            "Given Name",
            "Passport Number");

        PassengerParseResult result = _parser.ParseRows(
            "Sharma\tRahul\tZ1234567\r\nVerma\tPriya\tY7654321",
            template);

        Assert.True(result.Success);
        Assert.Equal(2, result.Profiles.Count);
        Assert.Equal("Rahul Sharma", result.Profiles[0].DisplayName);
        Assert.Equal("Priya Verma", result.Profiles[1].DisplayName);
    }

    [Fact]
    public void ParseRows_RejectsHeaderIncludedAsPassenger()
    {
        HeaderTemplate template = CreateTemplate(
            "Surname",
            "Passport Number");

        PassengerParseResult result = _parser.ParseRows(
            "Surname\tPassport Number\r\nSharma\tZ1234567",
            template);

        Assert.False(result.Success);
        Assert.Contains(
            result.Issues,
            issue => issue.Code == "HEADER_INCLUDED_AS_PASSENGER");
    }

    [Fact]
    public void ParseRows_RejectsEquivalentHeaderAliasesAsPassenger()
    {
        HeaderTemplate template = CreateTemplate(
            "Last Name",
            "Passport No.");

        PassengerParseResult result = _parser.ParseRows(
            "Surname\tPassport Number",
            template);

        Assert.False(result.Success);
        Assert.Contains(
            result.Issues,
            issue => issue.Code == "HEADER_INCLUDED_AS_PASSENGER");
    }

    [Fact]
    public void ParseRows_RejectsWidthMismatchRatherThanShiftingValues()
    {
        HeaderTemplate template = CreateTemplate(
            "Surname",
            "Given Name",
            "Passport Number");

        PassengerParseResult result = _parser.ParseRows(
            "Sharma\tZ1234567",
            template);

        Assert.False(result.Success);
        Assert.Empty(result.Profiles);
        Assert.Contains(result.Issues, issue => issue.Code == "WIDTH_MISMATCH");
    }

    [Fact]
    public void ParseHeaderAndRows_MapsHorizontalClipboardData()
    {
        PassengerParseResult result = _parser.ParseHeaderAndRows(
            "Surname\tGiven Name\tPassport No.\r\nSharma\tRahul\tZ1234567");

        Assert.True(result.Success);
        PassengerProfile profile = Assert.Single(result.Profiles);
        Assert.Equal("Sharma", profile.Fields["personal.surname"]);
        Assert.Equal("Rahul", profile.Fields["personal.given_name"]);
        Assert.Equal("Z1234567", profile.Fields["passport.number"]);
    }

    [Fact]
    public void ParseVerticalKeyValues_MapsOnePassenger()
    {
        PassengerParseResult result = _parser.ParseVerticalKeyValues(
            "Surname\tSharma\r\nGiven Name\tRahul\r\nPassport Number\tZ1234567");

        Assert.True(result.Success);
        Assert.Equal(PassengerParseMode.VerticalKeyValue, result.Mode);
        PassengerProfile profile = Assert.Single(result.Profiles);
        Assert.Equal("Sharma", profile.Fields["personal.surname"]);
        Assert.Equal("Rahul", profile.Fields["personal.given_name"]);
        Assert.Equal("Z1234567", profile.Fields["passport.number"]);
    }

    [Fact]
    public void ParseDirect_DetectsHorizontalAndVerticalPatterns()
    {
        PassengerParseResult horizontal = _parser.ParseDirect(
            "Surname\tPassport Number\r\nSharma\tZ1234567");
        PassengerParseResult vertical = _parser.ParseDirect(
            "Surname\tSharma\r\nPassport Number\tZ1234567\r\nEmail\trahul@example.com");

        Assert.True(horizontal.Success);
        Assert.Equal(PassengerParseMode.HeaderAndRows, horizontal.Mode);
        Assert.True(vertical.Success);
        Assert.Equal(PassengerParseMode.VerticalKeyValue, vertical.Mode);
    }

    [Fact]
    public void ParseDirect_RejectsStructurallyAmbiguousTwoColumnSelection()
    {
        PassengerParseResult result = _parser.ParseDirect(
            "Surname\tGiven Name\r\nPassport Number\tEmail");

        Assert.False(result.Success);
        Assert.Contains(result.Issues, issue => issue.Code == "AMBIGUOUS_LAYOUT");
    }

    [Fact]
    public void ParseHeaderAndRows_RejectsUnknownAndDuplicateHeaders()
    {
        PassengerParseResult unknown = _parser.ParseHeaderAndRows(
            "Surname\tMystery\r\nSharma\tABC");
        PassengerParseResult duplicate = _parser.ParseHeaderAndRows(
            "Passport Number\tPassport No.\r\nZ1234567\tZ1234567");

        Assert.False(unknown.Success);
        Assert.Contains(unknown.Issues, issue => issue.Code == "HEADER_UNKNOWN");
        Assert.False(duplicate.Success);
        Assert.Contains(duplicate.Issues, issue => issue.Code == "DUPLICATE_FIELD");
    }

    [Fact]
    public void ParseHeaderAndRows_RejectsRepeatedHeaderInPassengerRows()
    {
        PassengerParseResult result = _parser.ParseHeaderAndRows(
            "Surname\tPassport Number\r\nSurname\tPassport Number");

        Assert.False(result.Success);
        Assert.Contains(
            result.Issues,
            issue => issue.Code == "HEADER_INCLUDED_AS_PASSENGER");
    }

    [Fact]
    public void ParseHeaderAndRows_RequiresPassengerData()
    {
        PassengerParseResult result = _parser.ParseHeaderAndRows(
            "Surname\tPassport Number");

        Assert.False(result.Success);
        Assert.Contains(
            result.Issues,
            issue => issue.Code == "PASSENGER_ROW_REQUIRED");
    }

    [Fact]
    public void ParseVerticalKeyValues_RejectsDuplicateFieldAliases()
    {
        PassengerParseResult result = _parser.ParseVerticalKeyValues(
            "Passport Number\tZ1234567\r\nPassport No.\tY7654321");

        Assert.False(result.Success);
        Assert.Contains(result.Issues, issue => issue.Code == "DUPLICATE_FIELD");
    }

    [Fact]
    public void ParseRows_RejectsEmptyMappedPassengerRow()
    {
        HeaderTemplate template = CreateTemplate("Surname", "Passport Number");

        PassengerParseResult result = _parser.ParseRows("\t", template);

        Assert.False(result.Success);
        Assert.Contains(
            result.Issues,
            issue => issue.Code == "EMPTY_PASSENGER_ROW");
    }

    private static HeaderTemplate CreateTemplate(params string[] headers)
    {
        HeaderTemplateCreateResult result = HeaderTemplateFactory.Create(
            "opaque-workbook-key",
            "opaque-sheet-key",
            1,
            1,
            headers,
            CanonicalFieldCatalog.Default,
            createdAt: DateTimeOffset.UnixEpoch);
        Assert.True(result.Success);
        return Assert.IsType<HeaderTemplate>(result.Template);
    }
}
