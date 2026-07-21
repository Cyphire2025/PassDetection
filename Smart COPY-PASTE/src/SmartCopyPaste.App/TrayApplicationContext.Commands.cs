using SmartCopyPaste.App.Forms;
using SmartCopyPaste.App.Interop;
using SmartCopyPaste.App.Models;
using SmartCopyPaste.App.Services;
using SmartCopyPaste.Core.Headers;
using SmartCopyPaste.Core.Lifecycle;
using SmartCopyPaste.Core.Matching;
using SmartCopyPaste.Core.Parsing;
using SmartCopyPaste.Core.Session;

namespace SmartCopyPaste.App;

internal sealed partial class TrayApplicationContext
{
    private readonly record struct ActivePassengerSnapshot(
        long Generation,
        Guid ProfileId,
        long PasteCommitGeneration);

    private Task ExecuteWorkflowCommandAsync(
        HotkeyCommand command,
        CancellationToken cancellationToken) =>
        command switch
        {
            HotkeyCommand.CaptureHeaders => CaptureHeadersAsync(cancellationToken),
            HotkeyCommand.SmartCopy => SmartCopyAsync(cancellationToken),
            HotkeyCommand.SmartPaste => SmartPasteAsync(cancellationToken),
            HotkeyCommand.OpenPicker => OpenPickerAsync(null, cancellationToken),
            _ => Task.CompletedTask,
        };

    private async Task CaptureHeadersAsync(CancellationToken cancellationToken)
    {
        ExcelSelectionContext selection = await ExcelSelectionService
            .InspectAsync(userSecret, cancellationToken)
            .ConfigureAwait(true);
        IReadOnlyList<IReadOnlyList<string>> rows =
            await ReadSelectionRowsAsync(selection, cancellationToken).ConfigureAwait(true);
        if (rows.Count != 1)
        {
            throw new InvalidOperationException(
                "Select exactly one contiguous header row, then press Capture Headers again.");
        }

        IReadOnlyList<string> headers = rows[0];
        if (selection.IsExcelSelection &&
            (selection.RowCount != 1 || selection.ColumnCount != headers.Count))
        {
            throw new InvalidOperationException(
                "The Excel header selection changed. Select the row again and retry.");
        }

        string fallbackIdentity = Guid.NewGuid().ToString("N");
        string workbookIdentity = selection.IsExcelSelection
            ? selection.WorkbookIdentity
            : $"FALLBACK-{fallbackIdentity}";
        string worksheetIdentity = selection.IsExcelSelection
            ? selection.WorksheetIdentity
            : $"PROFILE-{fallbackIdentity}";
        int headerRow = selection.IsExcelSelection ? selection.FirstRow : 1;
        int firstColumn = selection.IsExcelSelection ? selection.FirstColumn : 1;
        string suggestedName = selection.IsExcelSelection
            ? selection.SuggestedTemplateName
            : $"Clipboard profile {settings.HeaderTemplates.Count + 1}";

        using var dialog = new HeaderMappingDialog(headers, suggestedName, catalog);
        DialogResult dialogResult = mainForm.Visible
            ? dialog.ShowDialog(mainForm)
            : dialog.ShowDialog();
        if (dialogResult != DialogResult.OK)
        {
            return;
        }

        HeaderTemplateCreateResult created = HeaderTemplateFactory.Create(
            workbookIdentity,
            worksheetIdentity,
            headerRow,
            firstColumn,
            headers.Select(static header => (string?)header).ToArray(),
            catalog,
            dialog.MappingOverrides);
        if (!created.Success || created.Template is null)
        {
            string message = (created.Issues.Count > 0 ? created.Issues[0].Message : null) ??
                "The header profile could not be created.";
            throw new InvalidOperationException(message);
        }

        HeaderTemplateRecord stored = HeaderTemplateAdapter.FromCore(
            created.Template,
            dialog.TemplateDisplayName,
            selection.IsExcelSelection && selection.SessionOnly);
        if (selection.IsExcelSelection)
        {
            settings.HeaderTemplates.RemoveAll(template =>
                string.Equals(
                    template.WorkbookIdentity,
                    stored.WorkbookIdentity,
                    StringComparison.Ordinal) &&
                string.Equals(
                    template.WorksheetIdentity,
                    stored.WorksheetIdentity,
                    StringComparison.Ordinal));
        }
        else
        {
            settings.HeaderTemplates.RemoveAll(template =>
                template.WorkbookIdentity.StartsWith("FALLBACK-", StringComparison.Ordinal) &&
                string.Equals(
                    template.DisplayName,
                    stored.DisplayName,
                    StringComparison.OrdinalIgnoreCase));
        }

        if (settings.ActiveFallbackTemplateId is not null &&
            !settings.HeaderTemplates.Any(template => string.Equals(
                template.TemplateId,
                settings.ActiveFallbackTemplateId,
                StringComparison.Ordinal)))
        {
            settings.ActiveFallbackTemplateId = null;
        }

        settings.HeaderTemplates.Add(stored);
        if (!selection.IsExcelSelection)
        {
            settings.ActiveFallbackTemplateId = stored.TemplateId;
        }

        SaveSettings();
        AddDiagnostic("HEADER_PROFILE_SAVED", "headers");
        ShowNotification(
            "Header profile saved",
            $"{headers.Count} columns are ready. Select passenger rows and press Ctrl+Alt+C.",
            ToolTipIcon.Info);
    }

    private async Task SmartCopyAsync(CancellationToken cancellationToken)
    {
        long startingSessionGeneration = session.Generation;
        ExcelSelectionContext selection = await ExcelSelectionService
            .InspectAsync(userSecret, cancellationToken)
            .ConfigureAwait(true);
        HeaderTemplateRecord template;
        IReadOnlyList<IReadOnlyList<string>> rows;
        int firstSourceRow;

        if (selection.IsExcelSelection)
        {
            template = settings.HeaderTemplates.FirstOrDefault(candidate =>
                string.Equals(
                    candidate.WorkbookIdentity,
                    selection.WorkbookIdentity,
                    StringComparison.Ordinal) &&
                string.Equals(
                    candidate.WorksheetIdentity,
                    selection.WorksheetIdentity,
                    StringComparison.Ordinal))
                ?? throw new InvalidOperationException(
                    "No saved header profile matches this workbook and sheet. Select the header row and press Ctrl+Alt+H first.");

            if (selection.FirstColumn != template.FirstColumn ||
                selection.ColumnCount != template.ColumnCount)
            {
                throw new InvalidOperationException(
                    $"Select exactly the {template.ColumnCount} passenger cells under the saved headers.");
            }

            int lastSelectedRow = selection.FirstRow + selection.RowCount - 1;
            if (template.HeaderRow >= selection.FirstRow &&
                template.HeaderRow <= lastSelectedRow)
            {
                throw new InvalidOperationException(
                    "Copy passenger rows only. Do not include the saved header row.");
            }

            bool headerStillMatches = await ExcelSelectionService
                .VerifyHeaderTemplateAsync(
                    userSecret,
                    selection,
                    template,
                    cancellationToken)
                .ConfigureAwait(true);
            if (!headerStillMatches)
            {
                throw new InvalidOperationException(
                    "The saved Excel headers changed or moved. Capture the header row again before copying passengers.");
            }

            rows = selection.DisplayRows;
            firstSourceRow = selection.FirstRow;
        }
        else
        {
            EnsureClipboardFallbackAllowed(selection);
            template = FindActiveFallbackTemplate()
                ?? throw new InvalidOperationException(
                    "Choose a named Header Profile from the tray before copying rows outside desktop Excel.");
            rows = await ReadSelectionRowsAsync(selection, cancellationToken).ConfigureAwait(true);
            firstSourceRow = 1;
        }

        string tsv = HeaderTemplateAdapter.SerializeRows(rows);
        HeaderTemplate coreTemplate = HeaderTemplateAdapter.ToCore(template);
        PassengerParseResult parsed = parser.ParseRows(tsv, coreTemplate);
        if (!parsed.Success)
        {
            throw new InvalidOperationException(
                (parsed.Issues.Count > 0 ? parsed.Issues[0].Message : null) ??
                "The passenger rows could not be read with the selected header profile.");
        }

        PassengerProfile[] profiles = parsed.Profiles
            .Select((profile, index) => PassengerProfile.Create(
                profile.Fields,
                firstSourceRow + index,
                coreTemplate.TemplateId,
                profile.DisplayName))
            .ToArray();
        if (session.Generation != startingSessionGeneration)
        {
            throw new InvalidOperationException(
                "Temporary passenger data was cleared while Smart Copy was running. No new passenger data was retained.");
        }

        SessionMutationResult result = session.SetProfiles(profiles);
        if (result.Status == SessionMutationStatus.Locked)
        {
            throw new InvalidOperationException(
                "The current passenger is locked. Unlock it before replacing the copied passenger list.");
        }

        AddDiagnostic("SMART_COPY_SUCCESS", "session");
        ShowNotification(
            profiles.Length == 1 ? "Passenger copied" : "Passengers copied",
            $"{profiles.Length} passenger row(s) and {profiles[0].Fields.Count} recognized field(s) are ready.",
            ToolTipIcon.Info);
    }

    private async Task SmartPasteAsync(CancellationToken cancellationToken)
    {
        EnsurePasteIsAvailable();
        ActivePassengerSnapshot passengerSnapshot = CaptureActivePassengerSnapshot();
        PassengerProfile active = session.Active!;
        FocusedFieldInspectionResult inspection = await automationInspector
            .InspectFocusedFieldAsync(cancellationToken)
            .ConfigureAwait(true);
        if (!inspection.Success || inspection.Field is null)
        {
            throw new InvalidOperationException(GetInspectionMessage(inspection.ErrorCode));
        }

        FocusedFieldSnapshot field = inspection.Field;
        EnsureEditableField(field);
        FocusedFieldContext context = CreateFocusedFieldContext(field);
        SmartCopyPaste.Core.Matching.FieldMatchResult match =
            matcher.Match(context, active.Fields.Keys);
        if (!match.CanPaste || match.CanonicalFieldId is null)
        {
            if (match.Status == FieldMatchStatus.Blocked)
            {
                throw new InvalidOperationException(
                    "Smart Paste is blocked for this protected, read-only, disabled, or unsupported field.");
            }

            if (match.Status == FieldMatchStatus.MissingValue)
            {
                throw new InvalidOperationException(
                    "The focused website field has no compatible value in the copied passenger row. No value was pasted; review the copied headers or use the field picker intentionally.");
            }

            FieldCandidateRankingResult ranking = matcher.RankCandidates(
                context,
                active.Fields.Keys);
            await OpenPickerAsync(
                field,
                cancellationToken,
                passengerSnapshot,
                context,
                ranking).ConfigureAwait(true);
            return;
        }

        TargetValueAdaptationResult adaptation = valueAdapter.Adapt(
            match.CanonicalFieldId,
            active.Fields[match.CanonicalFieldId],
            context);
        if (!adaptation.IsSafeToPaste)
        {
            throw new InvalidOperationException(GetUnsafeAdaptationMessage(adaptation));
        }

        string value = adaptation.Value;
        if (value.Any(char.IsControl))
        {
            FieldCandidateRankingResult ranking = matcher.RankCandidates(
                context,
                active.Fields.Keys);
            await OpenPickerAsync(
                field,
                cancellationToken,
                passengerSnapshot,
                context,
                ranking).ConfigureAwait(true);
            return;
        }

        await PrepareInjectionAsync(
            field,
            passengerSnapshot,
            cancellationToken).ConfigureAwait(true);
        bool inserted = await automationInspector
            .SetTargetValueAsync(
                field,
                value,
                pasteCommitGuard,
                passengerSnapshot.PasteCommitGeneration,
                cancellationToken)
            .ConfigureAwait(true);
        if (!inserted)
        {
            cancellationToken.ThrowIfCancellationRequested();
            throw new InvalidOperationException(
                "The website field changed or could not accept a safe exact-field update. No value was inserted; click the field and try again.");
        }

        if (adaptation.Status == TargetValueAdaptationStatus.Adapted)
        {
            AddDiagnostic("TARGET_VALUE_ADAPTED", "paste");
        }

        AddDiagnostic("SMART_PASTE_SUCCESS", "paste");
    }

    private async Task OpenPickerAsync(
        FocusedFieldSnapshot? knownField,
        CancellationToken cancellationToken,
        ActivePassengerSnapshot? expectedPassenger = null,
        FocusedFieldContext? knownContext = null,
        FieldCandidateRankingResult? knownRanking = null)
    {
        cancellationToken.ThrowIfCancellationRequested();
        EnsurePasteIsAvailable();
        ActivePassengerSnapshot passengerSnapshot =
            expectedPassenger ?? CaptureActivePassengerSnapshot();
        EnsureActivePassengerUnchanged(passengerSnapshot);
        PassengerProfile active = session.Active!;
        FocusedFieldSnapshot field;
        if (knownField is null)
        {
            FocusedFieldInspectionResult inspection = await automationInspector
                .InspectFocusedFieldAsync(cancellationToken)
                .ConfigureAwait(true);
            if (!inspection.Success || inspection.Field is null)
            {
                throw new InvalidOperationException(GetInspectionMessage(inspection.ErrorCode));
            }

            field = inspection.Field;
        }
        else
        {
            field = knownField;
        }

        EnsureEditableField(field);
        FocusedFieldContext context =
            knownContext ?? CreateFocusedFieldContext(field);
        cancellationToken.ThrowIfCancellationRequested();
        FieldCandidateRankingResult ranking =
            knownRanking ?? matcher.RankCandidates(context, active.Fields.Keys);
        if (ranking.Status == FieldCandidateRankingStatus.Blocked)
        {
            throw new InvalidOperationException(
                "Smart Paste is blocked for this protected or unsupported website control.");
        }

        IReadOnlyDictionary<string, string>? sourceHeaders = GetActiveSourceHeaders(active);
        cancellationToken.ThrowIfCancellationRequested();
        var picker = new ManualPickerForm(
            active,
            field,
            sourceHeaders,
            ranking,
            context,
            valueAdapter);
        using var pickerLifetime =
            new CancellationDisposalGate<ManualPickerForm>(
                picker,
                static form => form.RequestCancellation(),
                cancellationToken);
        _ = picker.Handle;
        pickerLifetime.ThrowIfCancellationRequested();
        DialogResult pickerResult = picker.ShowDialog();
        pickerLifetime.ThrowIfCancellationRequested();
        if (pickerResult != DialogResult.OK ||
            string.IsNullOrWhiteSpace(picker.SelectedFieldId))
        {
            return;
        }

        pickerLifetime.ThrowIfCancellationRequested();
        if (!active.Fields.TryGetValue(picker.SelectedFieldId, out string? value))
        {
            throw new InvalidOperationException(
                "The selected passenger field is no longer available.");
        }

        TargetValueAdaptationResult adaptation = valueAdapter.Adapt(
            picker.SelectedFieldId,
            value,
            context);
        if (!adaptation.IsSafeToPaste)
        {
            throw new InvalidOperationException(GetUnsafeAdaptationMessage(adaptation));
        }

        value = adaptation.Value;
        if (value.Any(char.IsControl))
        {
            throw new InvalidOperationException(
                "This value contains characters that cannot be inserted safely. Enter the value manually.");
        }

        bool restored = await automationInspector
            .RestoreFocusAsync(
                field.TargetToken,
                pasteCommitGuard,
                passengerSnapshot.PasteCommitGeneration,
                cancellationToken)
            .ConfigureAwait(true);
        if (!restored)
        {
            cancellationToken.ThrowIfCancellationRequested();
            throw new InvalidOperationException(
                "The website field changed while the picker was open. Click it and try again.");
        }

        await Task.Delay(60, cancellationToken).ConfigureAwait(true);
        await PrepareInjectionAsync(
            field,
            passengerSnapshot,
            cancellationToken).ConfigureAwait(true);
        bool inserted = await automationInspector
            .SetTargetValueAsync(
                field,
                value,
                pasteCommitGuard,
                passengerSnapshot.PasteCommitGeneration,
                cancellationToken)
            .ConfigureAwait(true);
        if (!inserted)
        {
            cancellationToken.ThrowIfCancellationRequested();
            throw new InvalidOperationException(
                "The website field changed or could not accept a safe exact-field update. No value was inserted; click the field and try again.");
        }

        if (picker.RememberChoice)
        {
            _ = targetMappings.Remember(field, picker.SelectedFieldId);
        }

        if (adaptation.Status == TargetValueAdaptationStatus.Adapted)
        {
            AddDiagnostic("TARGET_VALUE_ADAPTED", "paste");
        }

        AddDiagnostic("PICKER_PASTE_SUCCESS", "paste");
    }

    private FocusedFieldContext CreateFocusedFieldContext(
        FocusedFieldSnapshot field)
    {
        _ = targetMappings.TryGet(field, out string? savedCanonicalFieldId);
        return new FocusedFieldContext(
            field.ProcessName,
            field.ControlType,
            field.AccessibleName,
            field.AutomationId,
            field.HelpText,
            field.ClassName,
            field.IsPassword,
            field.IsReadOnly,
            field.IsEnabled,
            savedCanonicalFieldId,
            field.Placeholder,
            field.SectionHeading,
            field.InputType,
            field.FormatHint);
    }

    private ActivePassengerSnapshot CaptureActivePassengerSnapshot()
    {
        for (int attempt = 0; attempt < 2; attempt++)
        {
            long generation = session.Generation;
            PassengerProfile? active = session.Active;
            if (active is not null && generation == session.Generation)
            {
                return new ActivePassengerSnapshot(
                    generation,
                    active.ProfileId,
                    pasteCommitGuard.CaptureGeneration());
            }
        }

        throw new InvalidOperationException(
            "The active passenger changed. Review the active passenger and try again.");
    }

    private void EnsureActivePassengerUnchanged(ActivePassengerSnapshot snapshot)
    {
        PassengerProfile? current = session.Active;
        if (session.Generation != snapshot.Generation ||
            current is null ||
            current.ProfileId != snapshot.ProfileId)
        {
            throw new InvalidOperationException(
                "The active passenger changed before paste. No value was inserted; review the active passenger and try again.");
        }
    }

    private async Task PrepareInjectionAsync(
        FocusedFieldSnapshot field,
        ActivePassengerSnapshot passengerSnapshot,
        CancellationToken cancellationToken)
    {
        if (!await InputInjector
            .WaitForShortcutReleaseAsync(cancellationToken)
            .ConfigureAwait(true))
        {
            throw new InvalidOperationException("Release the shortcut keys and try again.");
        }

        bool stillFocused = await automationInspector
            .IsTargetStillFocusedAsync(field.TargetToken, cancellationToken)
            .ConfigureAwait(true);
        if (!stillFocused)
        {
            throw new InvalidOperationException(
                "The selected website field lost focus. Click it and try Smart Paste again.");
        }

        EnsurePasteIsAvailable();
        EnsureActivePassengerUnchanged(passengerSnapshot);
    }

    private async Task<IReadOnlyList<IReadOnlyList<string>>> ReadSelectionRowsAsync(
        ExcelSelectionContext selection,
        CancellationToken cancellationToken)
    {
        if (selection.IsExcelSelection)
        {
            return selection.DisplayRows;
        }

        EnsureClipboardFallbackAllowed(selection);
        DialogResult fallback = MessageBox.Show(
            "Exact Excel access is unavailable. Continue with the explicitly selected clipboard header profile?\n\nClipboard history may retain the source application's copy even though Smart COPY/PASTE immediately restores or clears the clipboard.",
            "Use clipboard fallback?",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning);
        if (fallback != DialogResult.Yes)
        {
            throw new InvalidOperationException(
                "The action was cancelled because exact Excel access was unavailable.");
        }

        _ = NativeMethods.SetForegroundWindow(selection.ForegroundWindow);
        await Task.Delay(100, cancellationToken).ConfigureAwait(true);
        InputInjector.EnsureTargetStillForeground(selection.ForegroundWindow);
        string text = await SecureClipboardService.CopyFocusedSelectionAsync(
            selection.ForegroundWindow,
            cancellationToken).ConfigureAwait(true);
        TabularParseResult table = parser.Parse(text);
        if (!table.Success)
        {
            throw new InvalidOperationException(
                (table.Issues.Count > 0 ? table.Issues[0].Message : null) ??
                "The copied selection is not a valid tabular range.");
        }

        return table.Rows;
    }

    private static void EnsureClipboardFallbackAllowed(
        ExcelSelectionContext selection)
    {
        if (selection.AllowsClipboardFallback)
        {
            return;
        }

        string message = selection.ErrorCode switch
        {
            "EXCEL_NO_SELECTION" =>
                "Excel did not expose a selected cell range. Select one rectangular range and try again.",
            "EXCEL_MULTI_AREA_SELECTION" =>
                "Multiple separate Excel areas are not supported. Select one contiguous rectangular range and try again.",
            "EXCEL_SELECTION_SIZE_INVALID" =>
                "The Excel selection is outside the safe limit. Select 1 to 100 rows and no more than 128 columns.",
            "EXCEL_MERGED_SELECTION" =>
                "Merged cells are not supported. Select an unmerged rectangular range and try again.",
            "EXCEL_DISPLAY_VALUE_OBSCURED" =>
                "Excel is displaying one or more selected values as ####. Widen those columns so every value is visible, then try again.",
            _ =>
                "Excel rejected the selected range. Select one visible, unmerged rectangular range and try again.",
        };
        throw new InvalidOperationException(message);
    }

    private HeaderTemplateRecord? FindActiveFallbackTemplate() =>
        settings.HeaderTemplates.FirstOrDefault(template =>
            string.Equals(
                template.TemplateId,
                settings.ActiveFallbackTemplateId,
                StringComparison.Ordinal));

    private IReadOnlyDictionary<string, string>? GetActiveSourceHeaders(PassengerProfile profile)
    {
        if (profile.HeaderTemplateId is null)
        {
            return null;
        }

        string templateId = profile.HeaderTemplateId.Value.ToString("N");
        HeaderTemplateRecord? template = settings.HeaderTemplates.FirstOrDefault(candidate =>
            string.Equals(candidate.TemplateId, templateId, StringComparison.OrdinalIgnoreCase));
        return template is null ? null : HeaderTemplateAdapter.GetSourceHeaders(template);
    }

    private void EnsurePasteIsAvailable()
    {
        if (paused)
        {
            throw new InvalidOperationException(
                "Smart Paste is paused. Press Ctrl+Alt+Space to resume.");
        }

        if (session.Active is null)
        {
            throw new InvalidOperationException(
                "No passenger data is copied. Select passenger rows and press Ctrl+Alt+C first.");
        }
    }

    private static void EnsureEditableField(FocusedFieldSnapshot field)
    {
        if (field.IsPassword)
        {
            throw new InvalidOperationException("Smart Paste is blocked for password fields.");
        }

        if (!field.IsEnabled)
        {
            throw new InvalidOperationException("The selected website field is disabled.");
        }

        if (field.IsReadOnly)
        {
            throw new InvalidOperationException("The selected website field is read-only.");
        }

        if (!field.IsEditable)
        {
            throw new InvalidOperationException(
                "This version supports standard editable text fields. Use the website normally for this control.");
        }
    }

    internal static bool IsStandardEditControlType(string controlType) =>
        string.Equals(
            controlType,
            "ControlType.Edit",
            StringComparison.OrdinalIgnoreCase) ||
        string.Equals(
            controlType,
            "Edit",
            StringComparison.OrdinalIgnoreCase);

    private static string GetUnsafeAdaptationMessage(
        TargetValueAdaptationResult adaptation) =>
        adaptation.Status == TargetValueAdaptationStatus.Ambiguous
            ? "The website requests a value format that cannot be converted safely. No value was pasted; enter this field manually."
            : "The copied value is not valid for this website field. No value was pasted; review the passenger data and enter this field manually.";

    private static string GetInspectionMessage(string? errorCode) =>
        errorCode switch
        {
            "TARGET_NOT_SUPPORTED_BROWSER" =>
                "Smart Paste currently supports standard fields in Google Chrome, Microsoft Edge, and Brave.",
            "TARGET_CAPTCHA_BLOCKED" or "TARGET_PROTECTED_BLOCKED" =>
                "Smart Paste never interacts with CAPTCHA, security-code, password, file-upload, or native date-picker controls.",
            _ =>
                "The selected website field could not be inspected. Click a standard text field and try again.",
        };
}
