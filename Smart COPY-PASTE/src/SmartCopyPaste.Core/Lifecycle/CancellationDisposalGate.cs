namespace SmartCopyPaste.Core.Lifecycle;

/// <summary>
/// Owns a disposable operation resource and requests cooperative shutdown when
/// its cancellation boundary is crossed. Callers must recheck the gate before
/// accessing operation-scoped data after a blocking or asynchronous boundary.
/// </summary>
/// <typeparam name="TResource">The disposable resource owned by the gate.</typeparam>
public sealed class CancellationDisposalGate<TResource> : IDisposable
    where TResource : class, IDisposable
{
    private readonly object syncRoot = new();
    private readonly CancellationToken cancellationToken;
    private readonly Action<TResource> requestCancellation;
    private CancellationTokenRegistration registration;
    private TResource? resource;
    private bool disposed;

    public CancellationDisposalGate(
        TResource resource,
        Action<TResource> requestCancellation,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(resource);
        ArgumentNullException.ThrowIfNull(requestCancellation);

        this.resource = resource;
        this.cancellationToken = cancellationToken;
        this.requestCancellation = requestCancellation;
        if (cancellationToken.IsCancellationRequested)
        {
            this.resource = null;
            disposed = true;
            resource.Dispose();
            cancellationToken.ThrowIfCancellationRequested();
        }

        try
        {
            registration = cancellationToken.Register(
                static state =>
                    ((CancellationDisposalGate<TResource>)state!)
                    .RequestCancellation(),
                this);
        }
        catch
        {
            this.resource = null;
            disposed = true;
            resource.Dispose();
            throw;
        }
    }

    public void ThrowIfCancellationRequested()
    {
        cancellationToken.ThrowIfCancellationRequested();
        ObjectDisposedException.ThrowIf(disposed, this);
    }

    public void Dispose()
    {
        TResource? resourceToDispose;
        lock (syncRoot)
        {
            if (disposed)
            {
                return;
            }

            disposed = true;
            resourceToDispose = resource;
            resource = null;
        }

        registration.Dispose();
        resourceToDispose?.Dispose();
    }

    private void RequestCancellation()
    {
        TResource? activeResource;
        lock (syncRoot)
        {
            if (disposed)
            {
                return;
            }

            activeResource = resource;
        }

        if (activeResource is not null)
        {
            requestCancellation(activeResource);
        }
    }
}
