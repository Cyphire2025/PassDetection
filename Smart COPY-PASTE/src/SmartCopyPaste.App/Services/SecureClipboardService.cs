using System.Runtime.InteropServices;
using SmartCopyPaste.App.Interop;

namespace SmartCopyPaste.App.Services;

internal sealed class SecureClipboardService
{
    private const int MaximumClipboardCharacters = 262_144;
    private static readonly string[] RestorableTextFormats =
    [
        DataFormats.UnicodeText,
        DataFormats.Text,
        DataFormats.CommaSeparatedValue,
        DataFormats.Html,
        DataFormats.Rtf,
    ];

    internal static async Task<string> CopyFocusedSelectionAsync(
        nint expectedForegroundWindow,
        CancellationToken cancellationToken)
    {
        if (!await InputInjector.WaitForShortcutReleaseAsync(cancellationToken).ConfigureAwait(true))
        {
            throw new InvalidOperationException("Release the shortcut keys and try again.");
        }

        InputInjector.EnsureTargetStillForeground(expectedForegroundWindow);
        DataObject? snapshot = TryCreateTextSnapshot();
        uint sequenceBeforeCopy = NativeMethods.GetClipboardSequenceNumber();
        uint selectionSequence = 0;
        try
        {
            InputInjector.SendControlShortcut(Keys.C, expectedForegroundWindow);

            long started = Environment.TickCount64;
            while (NativeMethods.GetClipboardSequenceNumber() == sequenceBeforeCopy)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (Environment.TickCount64 - started > 1500)
                {
                    throw new InvalidOperationException("The selected application did not place data on the clipboard.");
                }

                await Task.Delay(20, cancellationToken).ConfigureAwait(true);
            }

            selectionSequence = NativeMethods.GetClipboardSequenceNumber();
            string text = GetUnicodeTextWithRetry();
            uint sequenceAfterRead = NativeMethods.GetClipboardSequenceNumber();
            if (!IsStableReadSequence(selectionSequence, sequenceAfterRead))
            {
                throw new InvalidOperationException(
                    "The clipboard changed while Smart COPY/PASTE was reading the selected range. Nothing was imported; select the range and try again.");
            }

            if (string.IsNullOrWhiteSpace(text))
            {
                throw new InvalidOperationException("The copied selection does not contain tabular text.");
            }

            if (text.Length > MaximumClipboardCharacters)
            {
                throw new InvalidOperationException("The copied selection is too large. Select at most 100 passenger rows.");
            }

            return text;
        }
        finally
        {
            RestoreSnapshotIfStillOwned(snapshot, selectionSequence);
        }
    }

    internal static bool IsStableReadSequence(
        uint expectedSequence,
        uint observedSequence) =>
        expectedSequence != 0 &&
        expectedSequence == observedSequence;

    private static string GetUnicodeTextWithRetry()
    {
        for (int attempt = 0; attempt < 6; attempt++)
        {
            try
            {
                return Clipboard.ContainsText(TextDataFormat.UnicodeText)
                    ? Clipboard.GetText(TextDataFormat.UnicodeText)
                    : string.Empty;
            }
            catch (ExternalException) when (attempt < 5)
            {
                Thread.Sleep(20 * (attempt + 1));
            }
        }

        return string.Empty;
    }

    private static DataObject? TryCreateTextSnapshot()
    {
        IDataObject? source;
        try
        {
            source = Clipboard.GetDataObject();
        }
        catch (ExternalException)
        {
            return null;
        }

        if (source is null)
        {
            return null;
        }

        var snapshot = new DataObject();
        bool copiedAny = false;
        foreach (string format in RestorableTextFormats)
        {
            if (!source.GetDataPresent(format, autoConvert: false))
            {
                continue;
            }

            object? data = source.GetData(format, autoConvert: false);
            switch (data)
            {
                case string text:
                    snapshot.SetData(format, autoConvert: false, text);
                    copiedAny = true;
                    break;
                case MemoryStream stream:
                    snapshot.SetData(format, autoConvert: false, CloneStream(stream));
                    copiedAny = true;
                    break;
            }
        }

        return copiedAny ? snapshot : null;
    }

    private static void RestoreSnapshotIfStillOwned(DataObject? snapshot, uint ownedSequence)
    {
        if (ownedSequence == 0 || NativeMethods.GetClipboardSequenceNumber() != ownedSequence)
        {
            return;
        }

        try
        {
            if (snapshot is null)
            {
                Clipboard.Clear();
            }
            else
            {
                Clipboard.SetDataObject(snapshot, copy: true, retryTimes: 5, retryDelay: 20);
            }
        }
        catch (ExternalException)
        {
            // A concurrent application owns the clipboard now; do not overwrite it.
        }
    }

    private static MemoryStream CloneStream(MemoryStream source)
    {
        long originalPosition = source.Position;
        source.Position = 0;
        var clone = new MemoryStream();
        source.CopyTo(clone);
        clone.Position = 0;
        source.Position = originalPosition;
        return clone;
    }
}
