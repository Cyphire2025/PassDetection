using SmartCopyPaste.Core.Lifecycle;

namespace SmartCopyPaste.Core.Tests;

public sealed class CancellationDisposalGateTests
{
    [Fact]
    public void PreCanceledToken_DisposesResourceAndThrowsBeforeOperation()
    {
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        var resource = new TrackingDisposable();
        int cancellationRequests = 0;
        bool operationReached = false;

        _ = Assert.Throws<OperationCanceledException>(() =>
        {
            using var gate = new CancellationDisposalGate<TrackingDisposable>(
                resource,
                _ => cancellationRequests++,
                cancellation.Token);
            gate.ThrowIfCancellationRequested();
            operationReached = true;
        });

        Assert.True(resource.IsDisposed);
        Assert.Equal(0, cancellationRequests);
        Assert.False(operationReached);
    }

    [Fact]
    public void CancellationDuringOperation_RequestsShutdownAndGuardsDataAccess()
    {
        using var cancellation = new CancellationTokenSource();
        var resource = new TrackingDisposable();
        int cancellationRequests = 0;
        bool dataRead = false;
        var gate = new CancellationDisposalGate<TrackingDisposable>(
            resource,
            _ => cancellationRequests++,
            cancellation.Token);

        gate.ThrowIfCancellationRequested();
        cancellation.Cancel();
        _ = Assert.Throws<OperationCanceledException>(() =>
        {
            gate.ThrowIfCancellationRequested();
            dataRead = true;
        });

        Assert.Equal(1, cancellationRequests);
        Assert.False(dataRead);
        Assert.False(resource.IsDisposed);

        gate.Dispose();
        gate.Dispose();

        Assert.True(resource.IsDisposed);
        Assert.Equal(1, resource.DisposeCount);
    }

    private sealed class TrackingDisposable : IDisposable
    {
        public bool IsDisposed => DisposeCount > 0;

        public int DisposeCount { get; private set; }

        public void Dispose() => DisposeCount++;
    }
}
