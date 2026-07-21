using System.Security.Principal;

namespace SmartCopyPaste.App.Infrastructure;

internal sealed class SingleInstanceGuard : IDisposable
{
    private readonly Mutex? mutex;

    private SingleInstanceGuard(Mutex? mutex, bool isOwner)
    {
        this.mutex = mutex;
        IsOwner = isOwner;
    }

    public bool IsOwner { get; }

    public static SingleInstanceGuard TryAcquire()
    {
        string userIdentity = WindowsIdentity.GetCurrent().User?.Value ?? Environment.UserName;
        string safeIdentity = string.Concat(userIdentity.Select(static character =>
            char.IsLetterOrDigit(character) ? character : '-'));
        string name = $@"Local\SmartCopyPaste-{safeIdentity}";

        Mutex mutex = new(initiallyOwned: true, name, out bool createdNew);
        return new SingleInstanceGuard(mutex, createdNew);
    }

    public void Dispose()
    {
        if (IsOwner)
        {
            try
            {
                mutex?.ReleaseMutex();
            }
            catch (ApplicationException)
            {
                // The process is already shutting down and no longer owns the mutex.
            }
        }

        mutex?.Dispose();
    }
}
