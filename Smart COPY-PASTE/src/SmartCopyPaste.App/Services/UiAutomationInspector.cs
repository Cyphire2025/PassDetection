using System.Collections.Concurrent;
using System.Diagnostics;
using System.Windows.Automation;
using SmartCopyPaste.App.Interop;
using SmartCopyPaste.App.Models;
using SmartCopyPaste.Core.Normalization;
using SmartCopyPaste.Core.Security;

namespace SmartCopyPaste.App.Services;

internal sealed record FocusedFieldInspectionResult(
    FocusedFieldSnapshot? Field,
    string? ErrorCode)
{
    internal bool Success => Field is not null && ErrorCode is null;
}

internal sealed class UiAutomationOperationGate
{
    private const int Active = 0;
    private const int SideEffectStarted = 1;
    private const int Abandoned = 2;
    private const int Completed = 3;

    private readonly CancellationToken cancellationToken;
    private readonly long deadlineTimestamp;
    private int state;

    internal UiAutomationOperationGate(
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        ArgumentOutOfRangeException.ThrowIfLessThanOrEqual(timeout, TimeSpan.Zero);
        this.cancellationToken = cancellationToken;
        deadlineTimestamp = checked(
            Stopwatch.GetTimestamp() +
            (long)(timeout.TotalSeconds * Stopwatch.Frequency));
    }

    internal bool IsActive
    {
        get
        {
            if (Volatile.Read(ref state) != Active)
            {
                return false;
            }

            if (cancellationToken.IsCancellationRequested ||
                Stopwatch.GetTimestamp() >= deadlineTimestamp)
            {
                _ = TryAbandon();
                return false;
            }

            return true;
        }
    }

    internal bool SideEffectMayComplete
    {
        get
        {
            int current = Volatile.Read(ref state);
            return current is SideEffectStarted or Completed;
        }
    }

    internal bool TryBeginSideEffect()
    {
        if (!IsActive ||
            Interlocked.CompareExchange(
                ref state,
                SideEffectStarted,
                Active) != Active)
        {
            return false;
        }

        if (cancellationToken.IsCancellationRequested ||
            Stopwatch.GetTimestamp() >= deadlineTimestamp)
        {
            Interlocked.Exchange(ref state, Abandoned);
            return false;
        }

        return true;
    }

    internal bool TryAbandon() =>
        Interlocked.CompareExchange(ref state, Abandoned, Active) == Active;

    internal void CompleteSideEffect()
    {
        _ = Interlocked.CompareExchange(
            ref state,
            Completed,
            SideEffectStarted);
    }
}

internal sealed class UiAutomationInspector : IDisposable
{
    private static readonly TimeSpan OperationTimeout = TimeSpan.FromSeconds(3);
    private static readonly TimeSpan TargetLifetime = TimeSpan.FromMinutes(10);
    private static readonly AutomationProperty? AriaRoleProperty =
        AutomationProperty.LookupById(30101);
    private static readonly AutomationProperty? AriaPropertiesProperty =
        AutomationProperty.LookupById(30102);
    private static readonly string[] BlockedAccessibleTokens =
    [
        "captcha",
        "recaptcha",
        "i am not a robot",
        "security challenge",
    ];

    private readonly BlockingCollection<Action> workItems = new();
    private readonly Dictionary<string, StoredTarget> targets = new(StringComparer.Ordinal);
    private readonly Thread worker;
    private bool disposed;

    internal UiAutomationInspector()
    {
        worker = new Thread(WorkerLoop)
        {
            IsBackground = true,
            Name = "SmartCopyPaste.UIAutomationMTA",
        };
        worker.SetApartmentState(ApartmentState.MTA);
        worker.Start();
    }

    internal async Task<FocusedFieldInspectionResult> InspectFocusedFieldAsync(
        CancellationToken cancellationToken)
    {
        var completion = new TaskCompletionSource<FocusedFieldInspectionResult>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        Enqueue(
            () =>
            {
                try
                {
                    completion.TrySetResult(InspectFocusedField());
                }
                catch (Exception)
                {
                    completion.TrySetResult(new FocusedFieldInspectionResult(null, "UIA_UNAVAILABLE"));
                }
            },
            completion,
            cancellationToken);
        try
        {
            return await completion.Task
                .WaitAsync(OperationTimeout, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception)
        {
            return new FocusedFieldInspectionResult(null, "UIA_UNAVAILABLE");
        }
    }

    internal async Task<bool> RestoreFocusAsync(
        string targetToken,
        PasteCommitGuard commitGuard,
        long expectedCommitGeneration,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(targetToken);
        ArgumentNullException.ThrowIfNull(commitGuard);
        var operationGate = new UiAutomationOperationGate(
            OperationTimeout,
            cancellationToken);
        var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        Enqueue(
            () =>
            {
                bool restored = false;
                if (operationGate.IsActive &&
                    targets.TryGetValue(targetToken, out StoredTarget? target) &&
                    TryValidateTarget(
                        target,
                        requireFocused: false,
                        out _) &&
                    operationGate.TryBeginSideEffect())
                {
                    try
                    {
                        bool focusMatches = false;
                        bool executed = commitGuard.TryExecute(
                            expectedCommitGeneration,
                            () =>
                            {
                                _ = NativeMethods.SetForegroundWindow(target.ForegroundWindow);
                                target.Element.SetFocus();
                                AutomationElement focused = AutomationElement.FocusedElement;
                                focusMatches =
                                    NativeMethods.GetForegroundWindow() == target.ForegroundWindow &&
                                    Automation.Compare(focused, target.Element);
                            },
                            cancellationToken);
                        restored = executed && focusMatches;
                    }
                    catch (ElementNotAvailableException)
                    {
                        targets.Remove(targetToken);
                    }
                    catch (InvalidOperationException)
                    {
                        targets.Remove(targetToken);
                    }
                    catch (Exception)
                    {
                        targets.Remove(targetToken);
                    }
                    finally
                    {
                        operationGate.CompleteSideEffect();
                    }
                }

                completion.TrySetResult(restored);
            },
            completion,
            cancellationToken);
        return await AwaitSideEffectOperationAsync(
            completion.Task,
            operationGate,
            cancellationToken).ConfigureAwait(false);
    }

    internal async Task<bool> IsTargetStillFocusedAsync(
        string targetToken,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(targetToken);
        var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        Enqueue(
            () =>
            {
                bool matches = false;
                if (targets.TryGetValue(targetToken, out StoredTarget? target))
                {
                    try
                    {
                        matches = TryValidateTarget(
                            target,
                            requireFocused: true,
                            out _);
                    }
                    catch (ElementNotAvailableException)
                    {
                        targets.Remove(targetToken);
                    }
                    catch (InvalidOperationException)
                    {
                        targets.Remove(targetToken);
                    }
                    catch (Exception)
                    {
                        targets.Remove(targetToken);
                    }
                }

                completion.TrySetResult(matches);
            },
            completion,
            cancellationToken);
        try
        {
            return await completion.Task
                .WaitAsync(OperationTimeout, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception)
        {
            return false;
        }
    }

    internal async Task<bool> SetTargetValueAsync(
        FocusedFieldSnapshot expectedField,
        string value,
        PasteCommitGuard commitGuard,
        long expectedCommitGeneration,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(expectedField);
        ArgumentNullException.ThrowIfNull(value);
        ArgumentNullException.ThrowIfNull(commitGuard);
        if (value.Length is < 1 or > 2048 || value.Any(char.IsControl))
        {
            return false;
        }

        var operationGate = new UiAutomationOperationGate(
            OperationTimeout,
            cancellationToken);
        var completion = new TaskCompletionSource<bool>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        Enqueue(
            () =>
            {
                bool inserted = false;
                if (operationGate.IsActive &&
                    targets.TryGetValue(
                        expectedField.TargetToken,
                        out StoredTarget? target) &&
                    HasSameTargetSemantics(target.OriginalField, expectedField) &&
                    TryValidateTarget(
                        target,
                        requireFocused: true,
                        out ValuePattern? valuePattern) &&
                    valuePattern is not null &&
                    operationGate.TryBeginSideEffect())
                {
                    try
                    {
                        inserted = commitGuard.TryExecute(
                            expectedCommitGeneration,
                            () => valuePattern.SetValue(value),
                            cancellationToken);
                    }
                    catch (ElementNotAvailableException)
                    {
                        targets.Remove(expectedField.TargetToken);
                    }
                    catch (InvalidOperationException)
                    {
                        targets.Remove(expectedField.TargetToken);
                    }
                    catch (Exception)
                    {
                        targets.Remove(expectedField.TargetToken);
                    }
                    finally
                    {
                        operationGate.CompleteSideEffect();
                    }
                }

                completion.TrySetResult(inserted);
            },
            completion,
            cancellationToken);
        return await AwaitSideEffectOperationAsync(
            completion.Task,
            operationGate,
            cancellationToken).ConfigureAwait(false);
    }

    private static async Task<bool> AwaitSideEffectOperationAsync(
        Task<bool> operation,
        UiAutomationOperationGate operationGate,
        CancellationToken cancellationToken)
    {
        try
        {
            return await operation
                .WaitAsync(OperationTimeout, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (TimeoutException)
        {
            if (operationGate.TryAbandon())
            {
                return false;
            }

            return operationGate.SideEffectMayComplete &&
                await operation.ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            if (!operationGate.TryAbandon() &&
                operationGate.SideEffectMayComplete)
            {
                try
                {
                    _ = await operation.ConfigureAwait(false);
                }
                catch (Exception)
                {
                }
            }

            throw;
        }
        catch (Exception)
        {
            _ = operationGate.TryAbandon();
            return false;
        }
    }

    public void Dispose()
    {
        if (disposed)
        {
            return;
        }

        disposed = true;
        workItems.CompleteAdding();
        if (worker.Join(millisecondsTimeout: 750))
        {
            workItems.Dispose();
        }
    }

    private void WorkerLoop()
    {
        try
        {
            foreach (Action action in workItems.GetConsumingEnumerable())
            {
                try
                {
                    action();
                    RemoveExpiredTargets();
                }
                catch (Exception)
                {
                    // A faulty provider must not terminate the sole automation worker.
                }
            }
        }
        catch (ObjectDisposedException) when (disposed)
        {
        }
    }

    private FocusedFieldInspectionResult InspectFocusedField()
    {
        nint foregroundWindow = NativeMethods.GetForegroundWindow();
        if (!TryGetBrowserProcess(foregroundWindow, out string processName, out int processId))
        {
            return new FocusedFieldInspectionResult(null, "TARGET_NOT_SUPPORTED_BROWSER");
        }

        AutomationElement focused = AutomationElement.FocusedElement;
        if (focused is null)
        {
            return new FocusedFieldInspectionResult(null, "UIA_NO_FOCUSED_ELEMENT");
        }

        string token = Guid.NewGuid().ToString("N");
        FocusedFieldInspectionResult inspection = InspectElement(
            focused,
            processName,
            processId,
            foregroundWindow,
            token);
        if (inspection.Field is not null)
        {
            targets[token] = new StoredTarget(
                focused,
                foregroundWindow,
                DateTimeOffset.UtcNow.Add(TargetLifetime),
                inspection.Field);
        }

        return inspection;
    }

    private static FocusedFieldInspectionResult InspectElement(
        AutomationElement element,
        string processName,
        int processId,
        nint foregroundWindow,
        string targetToken)
    {
        AutomationElement.AutomationElementInformation current = element.Current;
        string accessibleName = NormalizeAccessibleLabelForTest(
            current.Name ?? string.Empty);
        if (accessibleName.Length == 0 && current.LabeledBy is AutomationElement labeledBy)
        {
            accessibleName = NormalizeAccessibleLabelForTest(
                labeledBy.Current.Name ?? string.Empty);
        }

        string automationId = current.AutomationId ?? string.Empty;
        string helpText = current.HelpText ?? string.Empty;
        string className = current.ClassName ?? string.Empty;
        string controlType = current.ControlType?.ProgrammaticName ?? string.Empty;
        string runtimeIdentity = GetRuntimeIdentity(element);
        string ariaProperties = GetCurrentStringProperty(
            element,
            AriaPropertiesProperty);
        string ariaRole = GetCurrentStringProperty(
            element,
            AriaRoleProperty);
        string placeholder = FirstNonBlank(
            ExtractAriaProperty(ariaProperties, "placeholder"),
            ExtractAriaProperty(ariaProperties, "aria-placeholder"));
        string inputType = FirstNonBlank(
            ExtractAriaProperty(ariaProperties, "type"),
            ExtractAriaProperty(ariaProperties, "input-type"),
            ExtractAriaProperty(ariaProperties, "autocomplete"),
            current.ItemType ?? string.Empty,
            ariaRole,
            current.LocalizedControlType ?? string.Empty);
        string formatHint = JoinMetadata(placeholder, helpText, current.ItemStatus ?? string.Empty);
        string sectionHeading = FindSectionHeading(element, accessibleName);
        bool isPassword = current.IsPassword;
        bool isEnabled = current.IsEnabled;
        bool isKeyboardFocusable = current.IsKeyboardFocusable;

        bool supportsValuePattern = element.TryGetCurrentPattern(
            ValuePattern.Pattern,
            out object? valuePatternObject);
        bool isReadOnly = true;
        if (supportsValuePattern && valuePatternObject is ValuePattern valuePattern)
        {
            isReadOnly = valuePattern.Current.IsReadOnly;
        }

        bool editableControl =
            current.ControlType == ControlType.Edit;
        bool isEditable =
            editableControl &&
            supportsValuePattern &&
            isEnabled &&
            isKeyboardFocusable &&
            !isReadOnly &&
            !isPassword;

        if (LengthExceeds(processName, 128) ||
            LengthExceeds(controlType, 128) ||
            LengthExceeds(accessibleName, 512) ||
            LengthExceeds(automationId, 512) ||
            LengthExceeds(helpText, 512) ||
            LengthExceeds(className, 256) ||
            LengthExceeds(runtimeIdentity, 256) ||
            LengthExceeds(placeholder, 512) ||
            LengthExceeds(sectionHeading, 512) ||
            LengthExceeds(inputType, 128) ||
            LengthExceeds(formatHint, 512))
        {
            return new FocusedFieldInspectionResult(null, "UIA_METADATA_TOO_LARGE");
        }

        if (ContainsBlockedToken(
            accessibleName,
            helpText,
            automationId,
            className,
            placeholder,
            sectionHeading,
            inputType,
            formatHint,
            ariaProperties))
        {
            return new FocusedFieldInspectionResult(null, "TARGET_PROTECTED_BLOCKED");
        }

        if (ContainsProtectedDirectFieldMetadata(
            accessibleName,
            automationId,
            helpText,
            className,
            placeholder,
            inputType,
            formatHint,
            ariaProperties))
        {
            return new FocusedFieldInspectionResult(null, "TARGET_PROTECTED_BLOCKED");
        }

        System.Windows.Rect bounds = current.BoundingRectangle;
        Rectangle boundingRectangle = bounds.IsEmpty
            ? Rectangle.Empty
            : Rectangle.Round(new RectangleF(
                (float)bounds.X,
                (float)bounds.Y,
                (float)bounds.Width,
                (float)bounds.Height));

        return new FocusedFieldInspectionResult(
            new FocusedFieldSnapshot(
                processName,
                processId,
                foregroundWindow,
                accessibleName,
                automationId,
                helpText,
                className,
                controlType,
                runtimeIdentity,
                isPassword,
                isEnabled,
                isReadOnly,
                isKeyboardFocusable,
                isEditable,
                placeholder,
                sectionHeading,
                inputType,
                formatHint,
                boundingRectangle,
                targetToken),
            null);
    }

    private void Enqueue<T>(
        Action action,
        TaskCompletionSource<T> completion,
        CancellationToken cancellationToken)
    {
        if (disposed)
        {
            completion.TrySetException(new ObjectDisposedException(nameof(UiAutomationInspector)));
            return;
        }

        if (cancellationToken.IsCancellationRequested)
        {
            completion.TrySetCanceled(cancellationToken);
            return;
        }

        try
        {
            workItems.Add(
                () =>
                {
                    try
                    {
                        action();
                    }
                    catch (Exception)
                    {
                        completion.TrySetException(
                            new InvalidOperationException("The UI Automation provider failed."));
                    }
                },
                cancellationToken);
        }
        catch (OperationCanceledException)
        {
            completion.TrySetCanceled(cancellationToken);
        }
        catch (InvalidOperationException)
        {
            completion.TrySetException(new ObjectDisposedException(nameof(UiAutomationInspector)));
        }
    }

    private static bool ContainsBlockedToken(params string[] metadata)
    {
        string combined = string.Join(" ", metadata);
        return BlockedAccessibleTokens.Any(token =>
            combined.Contains(token, StringComparison.OrdinalIgnoreCase));
    }

    private static bool ContainsProtectedDirectFieldMetadata(
        string accessibleName,
        string automationId,
        string helpText,
        string className,
        string placeholder,
        string inputType,
        string formatHint,
        string ariaProperties)
    {
        string directMetadata = DeterministicTextNormalizer.Normalize(
            string.Join(
                ' ',
                accessibleName,
                automationId,
                helpText,
                className,
                placeholder,
                inputType,
                formatHint,
                ariaProperties));
        string normalizedInputType =
            DeterministicTextNormalizer.Normalize(inputType);
        HashSet<string> tokens = directMetadata
            .Split(
                ' ',
                StringSplitOptions.RemoveEmptyEntries |
                    StringSplitOptions.TrimEntries)
            .ToHashSet(StringComparer.Ordinal);
        return ProtectedAuthenticationFieldClassifier.IsProtected(
                accessibleName,
                automationId,
                helpText,
                className,
                placeholder,
                inputType,
                formatHint,
                ariaProperties) ||
            normalizedInputType is "date" or "file" or "password" ||
            ContainsNormalizedPhrase(directMetadata, "type date") ||
            ContainsNormalizedPhrase(directMetadata, "type file") ||
            ContainsNormalizedPhrase(directMetadata, "type password") ||
            ContainsNormalizedPhrase(directMetadata, "choose file") ||
            tokens.Contains("file") &&
                tokens.Overlaps(["browse", "choose", "select", "upload"]) ||
            ContainsNormalizedPhrase(directMetadata, "date picker");
    }

    private bool TryValidateTarget(
        StoredTarget target,
        bool requireFocused,
        out ValuePattern? valuePattern)
    {
        valuePattern = null;
        bool Invalidate()
        {
            targets.Remove(target.OriginalField.TargetToken);
            return false;
        }

        if (target.IsExpired ||
            !TryGetBrowserProcess(
                target.ForegroundWindow,
                out string processName,
                out int processId) ||
            processId != target.OriginalField.ProcessId ||
            !string.Equals(
                processName,
                target.OriginalField.ProcessName,
                StringComparison.OrdinalIgnoreCase))
        {
            return Invalidate();
        }

        if (requireFocused)
        {
            if (NativeMethods.GetForegroundWindow() != target.ForegroundWindow)
            {
                return Invalidate();
            }

            AutomationElement focused = AutomationElement.FocusedElement;
            if (!Automation.Compare(focused, target.Element))
            {
                return Invalidate();
            }
        }

        FocusedFieldInspectionResult currentInspection = InspectElement(
            target.Element,
            processName,
            processId,
            target.ForegroundWindow,
            target.OriginalField.TargetToken);
        if (!currentInspection.Success ||
            currentInspection.Field is null ||
            !HasSameTargetSemantics(
                target.OriginalField,
                currentInspection.Field) ||
            !target.Element.TryGetCurrentPattern(
                ValuePattern.Pattern,
                out object? valuePatternObject) ||
            valuePatternObject is not ValuePattern currentValuePattern ||
            currentValuePattern.Current.IsReadOnly)
        {
            return Invalidate();
        }

        valuePattern = currentValuePattern;
        return true;
    }

    internal static bool HasSameTargetSemantics(
        FocusedFieldSnapshot expected,
        FocusedFieldSnapshot current) =>
        expected.ProcessId == current.ProcessId &&
        expected.ForegroundWindow == current.ForegroundWindow &&
        expected.IsPassword == current.IsPassword &&
        expected.IsEnabled == current.IsEnabled &&
        expected.IsReadOnly == current.IsReadOnly &&
        expected.IsKeyboardFocusable == current.IsKeyboardFocusable &&
        expected.IsEditable == current.IsEditable &&
        string.Equals(
            expected.ProcessName,
            current.ProcessName,
            StringComparison.OrdinalIgnoreCase) &&
        string.Equals(expected.AccessibleName, current.AccessibleName, StringComparison.Ordinal) &&
        string.Equals(expected.AutomationId, current.AutomationId, StringComparison.Ordinal) &&
        string.Equals(expected.HelpText, current.HelpText, StringComparison.Ordinal) &&
        string.Equals(expected.ClassName, current.ClassName, StringComparison.Ordinal) &&
        string.Equals(expected.ControlType, current.ControlType, StringComparison.Ordinal) &&
        string.Equals(expected.RuntimeIdentity, current.RuntimeIdentity, StringComparison.Ordinal) &&
        string.Equals(expected.Placeholder, current.Placeholder, StringComparison.Ordinal) &&
        string.Equals(expected.SectionHeading, current.SectionHeading, StringComparison.Ordinal) &&
        string.Equals(expected.InputType, current.InputType, StringComparison.Ordinal) &&
        string.Equals(expected.FormatHint, current.FormatHint, StringComparison.Ordinal) &&
        string.Equals(expected.TargetToken, current.TargetToken, StringComparison.Ordinal);

    private static bool ContainsNormalizedPhrase(
        string normalizedMetadata,
        string normalizedPhrase) =>
        $" {normalizedMetadata} ".Contains(
            $" {normalizedPhrase} ",
            StringComparison.Ordinal);

    private static string GetRuntimeIdentity(AutomationElement element)
    {
        try
        {
            int[] runtimeId = element.GetRuntimeId();
            if (runtimeId.Length is < 1 or > 32)
            {
                return string.Empty;
            }

            return string.Join(
                '.',
                runtimeId.Select(static value =>
                    value.ToString(
                        System.Globalization.CultureInfo.InvariantCulture)));
        }
        catch (ElementNotAvailableException)
        {
            return string.Empty;
        }
        catch (InvalidOperationException)
        {
            return string.Empty;
        }
    }

    internal static string NormalizeAccessibleLabelForTest(string value)
    {
        string cleaned = value.Trim();
        string[] removableSuffixes =
        [
            "(required)",
            "- required",
            ": required",
            " required",
            "(optional)",
            "- optional",
            ": optional",
            " optional",
        ];
        bool changed;
        do
        {
            changed = false;
            while (cleaned.EndsWith('*'))
            {
                cleaned = cleaned[..^1].TrimEnd();
                changed = true;
            }

            foreach (string suffix in removableSuffixes)
            {
                if (!cleaned.EndsWith(
                    suffix,
                    StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                cleaned = cleaned[..^suffix.Length].TrimEnd();
                changed = true;
                break;
            }
        }
        while (changed);

        return cleaned;
    }

    private static string FindSectionHeading(
        AutomationElement focused,
        string accessibleName)
    {
        try
        {
            AutomationElement? ancestor = focused;
            for (int depth = 0; depth < 4; depth++)
            {
                ancestor = TreeWalker.ControlViewWalker.GetParent(ancestor);
                if (ancestor is null)
                {
                    break;
                }

                AutomationElement.AutomationElementInformation information =
                    ancestor.Current;
                bool canDescribeSection =
                    information.ControlType == ControlType.Group ||
                    information.ControlType == ControlType.Pane;
                if (!canDescribeSection)
                {
                    continue;
                }

                string name = NormalizeAccessibleLabelForTest(
                    information.Name ?? string.Empty);
                if (name.Length > 0 &&
                    !string.Equals(
                        name,
                        accessibleName,
                        StringComparison.OrdinalIgnoreCase))
                {
                    return name;
                }
            }
        }
        catch (ElementNotAvailableException)
        {
        }
        catch (InvalidOperationException)
        {
        }
        catch (Exception)
        {
            // Browser providers can fail individual ancestor reads. The focused
            // element metadata remains useful without optional section context.
        }

        return string.Empty;
    }

    private static string GetCurrentStringProperty(
        AutomationElement element,
        AutomationProperty? property)
    {
        if (property is null)
        {
            return string.Empty;
        }

        object value = element.GetCurrentPropertyValue(property, ignoreDefaultValue: true);
        return value as string ?? string.Empty;
    }

    private static string ExtractAriaProperty(string ariaProperties, string propertyName)
    {
        foreach (string property in ariaProperties.Split(
            ';',
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            int separator = property.IndexOf('=');
            if (separator <= 0 ||
                !string.Equals(
                    property[..separator].Trim(),
                    propertyName,
                    StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            return property[(separator + 1)..].Trim().Trim('"');
        }

        return string.Empty;
    }

    private static string FirstNonBlank(params string[] candidates) =>
        candidates.FirstOrDefault(static candidate => !string.IsNullOrWhiteSpace(candidate))?.Trim() ??
        string.Empty;

    private static string JoinMetadata(params string[] values)
    {
        string joined = string.Join(
            " ",
            values
                .Where(static value => !string.IsNullOrWhiteSpace(value))
                .Select(static value => value.Trim())
                .Distinct(StringComparer.OrdinalIgnoreCase));
        return joined.Length <= 512 ? joined : joined[..512];
    }

    private static bool LengthExceeds(string value, int maximumLength) =>
        value.Length > maximumLength;

    private static bool TryGetBrowserProcess(
        nint foregroundWindow,
        out string processName,
        out int processId)
    {
        processName = string.Empty;
        processId = 0;
        _ = NativeMethods.GetWindowThreadProcessId(foregroundWindow, out uint nativeProcessId);
        if (nativeProcessId == 0 || nativeProcessId > int.MaxValue)
        {
            return false;
        }

        try
        {
            using Process process = Process.GetProcessById((int)nativeProcessId);
            processName = process.ProcessName;
            processId = process.Id;
            return IsSupportedBrowserProcessName(processName);
        }
        catch (ArgumentException)
        {
            return false;
        }
    }

    internal static bool IsSupportedBrowserProcessName(string processName) =>
        string.Equals(processName, "chrome", StringComparison.OrdinalIgnoreCase) ||
        string.Equals(processName, "msedge", StringComparison.OrdinalIgnoreCase) ||
        string.Equals(processName, "brave", StringComparison.OrdinalIgnoreCase);

    private void RemoveExpiredTargets()
    {
        string[] expired = targets
            .Where(static pair => pair.Value.IsExpired)
            .Select(static pair => pair.Key)
            .ToArray();
        foreach (string token in expired)
        {
            targets.Remove(token);
        }
    }

    private sealed record StoredTarget(
        AutomationElement Element,
        nint ForegroundWindow,
        DateTimeOffset ExpiresAt,
        FocusedFieldSnapshot OriginalField)
    {
        internal bool IsExpired => DateTimeOffset.UtcNow >= ExpiresAt;
    }
}
