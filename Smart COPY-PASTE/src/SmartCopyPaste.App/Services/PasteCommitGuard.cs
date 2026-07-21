namespace SmartCopyPaste.App.Services;

/// <summary>
/// Serializes a browser side effect with passenger/session security boundaries.
/// A boundary invalidation either happens before the side effect (which then
/// refuses to run) or waits for an already-started exact-target operation to
/// finish before temporary passenger data is cleared.
/// </summary>
internal sealed class PasteCommitGuard
{
    private readonly object syncRoot = new();
    private long generation;

    internal long CaptureGeneration()
    {
        lock (syncRoot)
        {
            return generation;
        }
    }

    internal bool TryExecute(
        long expectedGeneration,
        Action sideEffect,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(sideEffect);
        lock (syncRoot)
        {
            if (generation != expectedGeneration ||
                cancellationToken.IsCancellationRequested)
            {
                return false;
            }

            sideEffect();
            return true;
        }
    }

    internal void Invalidate()
    {
        lock (syncRoot)
        {
            generation = generation == long.MaxValue
                ? 0
                : generation + 1;
        }
    }
}
