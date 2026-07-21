using System.Security.Cryptography;
using System.Runtime.InteropServices;
using SmartCopyPaste.App.Forms;
using SmartCopyPaste.App.Interop;
using SmartCopyPaste.App.Models;
using SmartCopyPaste.Core.Catalog;
using SmartCopyPaste.Core.Configuration;
using SmartCopyPaste.Core.Headers;
using SmartCopyPaste.Core.Matching;
using SmartCopyPaste.Core.Parsing;
using SmartCopyPaste.Core.Session;

namespace SmartCopyPaste.App.Services;

internal static class SelfTestRunner
{
    internal static int Run()
    {
        _ = NativeMethods.AttachConsole(unchecked((uint)-1));
        string? temporaryDirectory = null;
        try
        {
            int expectedInputSize = IntPtr.Size == 8 ? 40 : 28;
            if (Marshal.SizeOf<NativeMethods.Input>() != expectedInputSize)
            {
                Console.Error.WriteLine("SELF-TEST FAILED: Win32 INPUT layout.");
                return 8;
            }

            byte[] source = RandomNumberGenerator.GetBytes(32);
            byte[] protectedData = NativeMethods.ProtectCurrentUser(source);
            byte[] roundTrip = NativeMethods.UnprotectCurrentUser(protectedData);
            if (!CryptographicOperations.FixedTimeEquals(source, roundTrip))
            {
                Console.Error.WriteLine("SELF-TEST FAILED: DPAPI round-trip mismatch.");
                return 2;
            }

            if (PersistedAppSettings.CreateDefaultHotkeys().Count != 8)
            {
                Console.Error.WriteLine("SELF-TEST FAILED: default hotkey catalog is incomplete.");
                return 3;
            }

            string[] invalidExcelSelectionCodes =
            [
                "EXCEL_NO_SELECTION",
                "EXCEL_MULTI_AREA_SELECTION",
                "EXCEL_SELECTION_SIZE_INVALID",
                "EXCEL_MERGED_SELECTION",
                "EXCEL_DISPLAY_VALUE_OBSCURED",
                "EXCEL_UNKNOWN_FAILURE",
            ];
            if (!ExcelSelectionContext.NotExcel(nint.Zero).AllowsClipboardFallback ||
                !ExcelSelectionContext.Failure(
                    nint.Zero,
                    "EXCEL_TIMEOUT").AllowsClipboardFallback ||
                !ExcelSelectionContext.Failure(
                    nint.Zero,
                    "EXCEL_SELECTION_UNAVAILABLE").AllowsClipboardFallback ||
                !ExcelSelectionContext.Failure(
                    nint.Zero,
                    "EXCEL_FOREGROUND_INSTANCE_MISMATCH").AllowsClipboardFallback ||
                invalidExcelSelectionCodes.Any(code =>
                    ExcelSelectionContext.Failure(
                        nint.Zero,
                        code).AllowsClipboardFallback))
            {
                Console.Error.WriteLine("SELF-TEST FAILED: Excel clipboard fallback policy.");
                return 22;
            }

            if (!SecureClipboardService.IsStableReadSequence(41, 41) ||
                SecureClipboardService.IsStableReadSequence(41, 42) ||
                SecureClipboardService.IsStableReadSequence(0, 0))
            {
                Console.Error.WriteLine("SELF-TEST FAILED: clipboard sequence guard.");
                return 23;
            }

            string[] liveHeaderFixture =
            [
                "Group",
                "Destination",
                "Travel Date",
                "Return Date",
                "Client Name",
                "Email",
                "Phone",
                "Nearest International Airport",
                "Nearest Domestic Airport",
                "Meal Preference",
                "Surname",
                "Given Names",
                "Passport Number",
                "Nationality",
                "Date of Birth",
                "Date of Issue",
                "Date of Expiry",
                "Sex",
            ];
            using (var headerDialog = new HeaderMappingDialog(
                liveHeaderFixture,
                "Header dialog self-test",
                CanonicalFieldCatalog.Default))
            {
                bool shown = false;
                headerDialog.Opacity = 0;
                headerDialog.ShowInTaskbar = false;
                headerDialog.StartPosition = FormStartPosition.Manual;
                headerDialog.Location = new Point(-32_000, -32_000);
                headerDialog.Shown += (_, _) =>
                {
                    shown = true;
                    headerDialog.BeginInvoke(headerDialog.Close);
                };
                _ = headerDialog.ShowDialog();
                if (!shown || headerDialog.HadMappingDataError)
                {
                    Console.Error.WriteLine("SELF-TEST FAILED: header mapping dialog.");
                    return 9;
                }
            }

            Dictionary<int, HeaderMappingOverride> liveHeaderOverrides = liveHeaderFixture
                .Select((header, index) => new
                {
                    Header = header,
                    Index = index,
                    Match = CanonicalFieldCatalog.Default.ResolveHeader(header),
                })
                .Where(static item => item.Match.Status != AliasMatchStatus.Unique)
                .ToDictionary(
                    static item => item.Index,
                    static item => new HeaderMappingOverride(
                        HeaderMappingKind.Custom,
                        HeaderTemplateFactory.CreateCustomFieldId(item.Header)));
            HeaderTemplateCreateResult liveHeaderTemplate = HeaderTemplateFactory.Create(
                "SELF-TEST-WORKBOOK",
                "SELF-TEST-SHEET",
                4,
                1,
                liveHeaderFixture,
                CanonicalFieldCatalog.Default,
                liveHeaderOverrides);
            if (!liveHeaderTemplate.Success)
            {
                Console.Error.WriteLine("SELF-TEST FAILED: live header template fixture.");
                return 10;
            }

            if (!string.Equals(
                    ExcelSelectionService.ResolveWorksheetIdentityName(
                        string.Empty,
                        "Passenger Data"),
                    "Passenger Data",
                    StringComparison.Ordinal) ||
                !string.Equals(
                    ExcelSelectionService.ResolveWorksheetIdentityName(
                        "   ",
                        "   "),
                    "Sheet",
                    StringComparison.Ordinal))
            {
                Console.Error.WriteLine("SELF-TEST FAILED: Excel worksheet identity fallback.");
                return 11;
            }

            SettingsValidationResult settingsValidation = SettingsValidator.Validate(
                HotkeySettingsAdapter.ToCoreSettings(new PersistedAppSettings()));
            if (!settingsValidation.IsValid)
            {
                Console.Error.WriteLine("SELF-TEST FAILED: default settings are invalid.");
                return 4;
            }

            var parser = new TabularDataParser(CanonicalFieldCatalog.Default);
            PassengerParseResult parsed = parser.ParseDirect(
                "Surname\tPassport Number\r\nSharma\tZ1234567");
            if (!parsed.Success || parsed.Profiles.Count != 1)
            {
                Console.Error.WriteLine("SELF-TEST FAILED: deterministic passenger parser.");
                return 5;
            }

            var matcher = new FocusedFieldMatcher(CanonicalFieldCatalog.Default);
            SmartCopyPaste.Core.Matching.FieldMatchResult match = matcher.Match(
                new FocusedFieldContext(
                    "chrome.exe",
                    "Edit",
                    AccessibleName: "Passport Number"),
                parsed.Profiles[0].Fields.Keys);
            if (!match.CanPaste ||
                !string.Equals(match.CanonicalFieldId, "passport.number", StringComparison.Ordinal))
            {
                Console.Error.WriteLine("SELF-TEST FAILED: deterministic field matcher.");
                return 6;
            }

            FocusedFieldSnapshot semanticBaseline = CreateFocusedFieldSnapshot();
            var abandonedOperation = new UiAutomationOperationGate(
                TimeSpan.FromMinutes(1),
                CancellationToken.None);
            bool abandonedBeforeSideEffect = abandonedOperation.TryAbandon();
            var expiredOperation = new UiAutomationOperationGate(
                TimeSpan.FromMilliseconds(1),
                CancellationToken.None);
            Thread.Sleep(5);
            if (!UiAutomationInspector.IsSupportedBrowserProcessName("brave") ||
                UiAutomationInspector.IsSupportedBrowserProcessName("firefox") ||
                !string.Equals(
                    UiAutomationInspector.NormalizeAccessibleLabelForTest(
                        "Telephone number * (required)"),
                    "Telephone number",
                    StringComparison.Ordinal) ||
                !TrayApplicationContext.IsStandardEditControlType(
                    "ControlType.Edit") ||
                TrayApplicationContext.IsStandardEditControlType(
                    "ControlType.Document") ||
                !UiAutomationInspector.HasSameTargetSemantics(
                    semanticBaseline,
                    semanticBaseline with
                    {
                        BoundingRectangle = new Rectangle(200, 200, 300, 40),
                    }) ||
                UiAutomationInspector.HasSameTargetSemantics(
                    semanticBaseline,
                    semanticBaseline with
                    {
                        IsPassword = true,
                    }) ||
                UiAutomationInspector.HasSameTargetSemantics(
                    semanticBaseline,
                    semanticBaseline with
                    {
                        AccessibleName = "Changed target",
                    }) ||
                !abandonedBeforeSideEffect ||
                abandonedOperation.TryBeginSideEffect() ||
                expiredOperation.TryBeginSideEffect())
            {
                Console.Error.WriteLine(
                    "SELF-TEST FAILED: browser metadata and edit-control safety.");
                return 12;
            }

            var commitGuard = new PasteCommitGuard();
            long allowedCommitGeneration = commitGuard.CaptureGeneration();
            bool committed = false;
            if (!commitGuard.TryExecute(
                    allowedCommitGeneration,
                    () => committed = true,
                    CancellationToken.None) ||
                !committed)
            {
                Console.Error.WriteLine(
                    "SELF-TEST FAILED: paste commit guard initial generation.");
                return 20;
            }

            commitGuard.Invalidate();
            committed = false;
            if (commitGuard.TryExecute(
                    allowedCommitGeneration,
                    () => committed = true,
                    CancellationToken.None) ||
                committed)
            {
                Console.Error.WriteLine(
                    "SELF-TEST FAILED: stale paste commit generation.");
                return 21;
            }

            FocusedFieldSnapshot telephoneField = CreateFocusedFieldSnapshot();
            var targetMappingStore = new SessionTargetMappingStore();
            if (!targetMappingStore.Remember(
                    telephoneField,
                    "contact.mobile") ||
                !targetMappingStore.TryGet(
                    telephoneField,
                    out string? rememberedFieldId) ||
                !string.Equals(
                    rememberedFieldId,
                    "contact.mobile",
                    StringComparison.Ordinal) ||
                targetMappingStore.TryGet(
                    telephoneField with
                    {
                        ForegroundWindow = new nint(0x4567),
                    },
                    out _) ||
                targetMappingStore.TryGet(
                    telephoneField with
                    {
                        RuntimeIdentity = "42.999",
                    },
                    out _) ||
                targetMappingStore.TryGet(
                    telephoneField with
                    {
                        Placeholder = "Different exact target",
                    },
                    out _) ||
                targetMappingStore.TryGet(
                    telephoneField with
                    {
                        SectionHeading = "Different section",
                    },
                    out _))
            {
                Console.Error.WriteLine(
                    "SELF-TEST FAILED: session target mapping boundary.");
                return 13;
            }

            targetMappingStore.Clear();
            if (targetMappingStore.TryGet(telephoneField, out _))
            {
                Console.Error.WriteLine(
                    "SELF-TEST FAILED: session target mapping clear.");
                return 14;
            }

            var telephoneContext = new FocusedFieldContext(
                "chrome",
                "ControlType.Edit",
                AccessibleName: "Telephone number",
                Placeholder: "Telephone number");
            var pickerProfile = PassengerProfile.Create(
                new Dictionary<string, string>(StringComparer.Ordinal)
                {
                    ["contact.mobile"] = "+91 98765 43210",
                    ["contact.landline"] = "011 2345 6789",
                    ["passport.number"] = "Z1234567",
                    ["personal.surname"] = "Sharma",
                },
                sourceRowNumber: 5,
                displayName: "Picker self-test passenger");
            FieldCandidateRankingResult telephoneRanking =
                matcher.RankCandidates(
                    telephoneContext,
                    pickerProfile.Fields.Keys);
            string[] telephoneCandidateIds = telephoneRanking.Candidates
                .Select(static candidate => candidate.CanonicalFieldId)
                .OrderBy(static fieldId => fieldId, StringComparer.Ordinal)
                .ToArray();
            if (!telephoneRanking.HasRelatedCandidates ||
                !telephoneCandidateIds.SequenceEqual(
                    ["contact.landline", "contact.mobile"],
                    StringComparer.Ordinal))
            {
                Console.Error.WriteLine(
                    "SELF-TEST FAILED: telephone candidate ranking.");
                return 15;
            }

            using (var picker = new ManualPickerForm(
                pickerProfile,
                telephoneField,
                ranking: telephoneRanking,
                fieldContext: telephoneContext,
                targetValueAdapter: new TargetValueAdapter(
                    CanonicalFieldCatalog.Default)))
            {
                if (!picker.ShowingRecommendationsOnly ||
                    picker.VisibleResultCount != 2 ||
                    !picker.RememberChoice)
                {
                    Console.Error.WriteLine(
                        "SELF-TEST FAILED: focused picker defaults.");
                    return 16;
                }

                picker.SetSearchTextForSelfTest("passport");
                if (picker.VisibleResultCount != 0 ||
                    !picker.ShowingRecommendationsOnly)
                {
                    Console.Error.WriteLine(
                        "SELF-TEST FAILED: picker recommendation scope.");
                    return 17;
                }

                picker.SetSearchTextForSelfTest(string.Empty);
                if (!SmokeFormAtClientSizes(
                    picker,
                    new Size(700, 500),
                    new Size(900, 650)))
                {
                    Console.Error.WriteLine(
                        "SELF-TEST FAILED: picker responsive layout.");
                    return 18;
                }
            }

            if (ResponsiveWindowLayout.ScaleMetric(38, 96) != 38 ||
                ResponsiveWindowLayout.ScaleMetric(38, 144) != 57 ||
                ResponsiveWindowLayout.ScaleMetric(34, 144) != 51 ||
                !SmokeRemainingForms(pickerProfile))
            {
                Console.Error.WriteLine(
                    "SELF-TEST FAILED: responsive form and DPI metrics.");
                return 19;
            }

            temporaryDirectory = Path.Combine(
                Path.GetTempPath(),
                $"SmartCopyPaste-self-test-{Guid.NewGuid():N}");
            var store = new ProtectedSettingsStore(temporaryDirectory);
            string sessionTemplateId = Guid.NewGuid().ToString("N");
            string persistentTemplateId = Guid.NewGuid().ToString("N");
            var persistenceSettings = new PersistedAppSettings
            {
                ActiveFallbackTemplateId = sessionTemplateId,
                HeaderTemplates =
                [
                    CreatePersistenceTestTemplate(
                        sessionTemplateId,
                        "SESSION-ONLY-SENTINEL",
                        sessionOnly: true),
                    CreatePersistenceTestTemplate(
                        persistentTemplateId,
                        "PERSISTENT-SENTINEL",
                        sessionOnly: false),
                ],
            };
            byte[] generatedSecret = ProtectedSettingsStore.GetUserSecret(persistenceSettings);
            CryptographicOperations.ZeroMemory(generatedSecret);
            store.Save(persistenceSettings);
            string persistedJson = File.ReadAllText(store.SettingsPath);
            if (persistedJson.Contains("SESSION-ONLY-SENTINEL", StringComparison.Ordinal) ||
                !persistedJson.Contains("PERSISTENT-SENTINEL", StringComparison.Ordinal) ||
                persistenceSettings.HeaderTemplates.Count != 2)
            {
                Console.Error.WriteLine("SELF-TEST FAILED: session-only persistence boundary.");
                return 7;
            }

            Console.WriteLine("SELF-TEST PASSED");
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"SELF-TEST FAILED: {exception.GetType().Name}");
            return 1;
        }
        finally
        {
            if (temporaryDirectory is not null &&
                Directory.Exists(temporaryDirectory))
            {
                try
                {
                    Directory.Delete(temporaryDirectory, recursive: true);
                }
                catch (IOException)
                {
                }
                catch (UnauthorizedAccessException)
                {
                }
            }
        }
    }

    private static FocusedFieldSnapshot CreateFocusedFieldSnapshot() =>
        new(
            "chrome",
            4242,
            new nint(0x1234),
            "Telephone number",
            "traveler-phone",
            "Enter a contact number",
            "form-control",
            "ControlType.Edit",
            "42.7.19",
            IsPassword: false,
            IsEnabled: true,
            IsReadOnly: false,
            IsKeyboardFocusable: true,
            IsEditable: true,
            Placeholder: "Telephone number",
            SectionHeading: "Contact details",
            InputType: "tel",
            FormatHint: string.Empty,
            BoundingRectangle: new Rectangle(120, 160, 260, 36),
            TargetToken: "self-test-target");

    private static bool SmokeRemainingForms(PassengerProfile profile)
    {
        using var main = new MainForm();
        var session = new PassengerSession();
        _ = session.SetProfiles([profile]);
        main.UpdateState(
            session,
            paused: false,
            startsWithWindows: false,
            commandInProgress: false);
        if (!SmokeFormAtClientSizes(
            main,
            new Size(780, 560),
            new Size(1040, 720)))
        {
            return false;
        }

        using var header = new HeaderMappingDialog(
            ["Surname", "Agency Internal Reference", "Passport Number"],
            "Responsive self-test",
            CanonicalFieldCatalog.Default);
        if (!SmokeFormAtClientSizes(
            header,
            new Size(700, 500),
            new Size(920, 680)))
        {
            return false;
        }

        using var shortcuts = new ShortcutSettingsForm(
            PersistedAppSettings.CreateDefaultHotkeys());
        if (!SmokeFormAtClientSizes(
            shortcuts,
            new Size(700, 520),
            new Size(760, 620)))
        {
            return false;
        }

        using var diagnostics = new DiagnosticsForm(
            "{\r\n  \"status\": \"self-test\"\r\n}");
        return SmokeFormAtClientSizes(
            diagnostics,
            new Size(700, 500),
            new Size(820, 600));
    }

    private static bool SmokeFormAtClientSizes(
        Form form,
        params Size[] clientSizes)
    {
        form.Opacity = 0;
        form.ShowInTaskbar = false;
        form.StartPosition = FormStartPosition.Manual;
        form.Location = new Point(-32_000, -32_000);
        form.Show();
        try
        {
            foreach (Size clientSize in clientSizes)
            {
                form.ClientSize = clientSize;
                PerformLayoutRecursively(form);
                Application.DoEvents();
                if (form.Font.SizeInPoints < 10.4F ||
                    !ValidateVisibleControlTree(form))
                {
                    return false;
                }
            }

            return true;
        }
        finally
        {
            form.Hide();
        }
    }

    private static void PerformLayoutRecursively(Control control)
    {
        control.PerformLayout();
        foreach (Control child in control.Controls)
        {
            PerformLayoutRecursively(child);
        }
    }

    private static bool ValidateVisibleControlTree(Control parent)
    {
        foreach (Control child in parent.Controls)
        {
            if (!child.Visible)
            {
                continue;
            }

            if (child.Width <= 0 || child.Height <= 0)
            {
                return false;
            }

            if (parent is not ScrollableControl { AutoScroll: true } &&
                (child.Left < -1 ||
                 child.Top < -1 ||
                 child.Right > parent.ClientSize.Width + 1 ||
                 child.Bottom > parent.ClientSize.Height + 1))
            {
                return false;
            }

            if (child is DataGridView grid)
            {
                int columnWidth = grid.Columns
                    .Cast<DataGridViewColumn>()
                    .Where(static column => column.Visible)
                    .Sum(static column => column.Width);
                int expectedHeaderHeight =
                    ResponsiveWindowLayout.ScaleMetric(38, grid.DeviceDpi);
                if (columnWidth > grid.ClientSize.Width + 2 ||
                    grid.ColumnHeadersHeight < expectedHeaderHeight ||
                    grid.RowTemplate.Height <
                        ResponsiveWindowLayout.ScaleMetric(
                            34,
                            grid.DeviceDpi))
                {
                    return false;
                }

                continue;
            }

            if (!ValidateVisibleControlTree(child))
            {
                return false;
            }
        }

        return true;
    }

    private static HeaderTemplateRecord CreatePersistenceTestTemplate(
        string templateId,
        string workbookIdentity,
        bool sessionOnly) =>
        new()
        {
            TemplateId = templateId,
            DisplayName = sessionOnly ? "Session profile" : "Persistent profile",
            WorkbookIdentity = workbookIdentity,
            WorksheetIdentity = $"{workbookIdentity}-SHEET",
            HeaderRow = 1,
            FirstColumn = 1,
            ColumnCount = 1,
            HeaderFingerprint = HeaderFingerprint.Compute(["Surname"]),
            SessionOnly = sessionOnly,
            Columns =
            [
                new HeaderColumnRecord
                {
                    Offset = 0,
                    OriginalHeader = "Surname",
                    CanonicalFieldId = "personal.surname",
                    Ignored = false,
                },
            ],
        };
}
