using SmartCopyPaste.App.Infrastructure;
using SmartCopyPaste.App.Services;

namespace SmartCopyPaste.App;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        Application.SetDefaultFont(new Font("Segoe UI", 10.5F, FontStyle.Regular, GraphicsUnit.Point));

        if (args.Any(static argument => string.Equals(argument, "--self-test", StringComparison.OrdinalIgnoreCase)))
        {
            return SelfTestRunner.Run();
        }

        using SingleInstanceGuard instance = SingleInstanceGuard.TryAcquire();
        if (!instance.IsOwner)
        {
            MessageBox.Show(
                "Smart COPY/PASTE is already running in the notification area.",
                "Smart COPY/PASTE",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
            return 0;
        }

        bool startInBackground = args.Any(static argument =>
            string.Equals(
                argument,
                "--startup",
                StringComparison.OrdinalIgnoreCase) ||
            string.Equals(
                argument,
                "--background",
                StringComparison.OrdinalIgnoreCase));
        using TrayApplicationContext context = new(
            showMainWindow: !startInBackground);
        Application.Run(context);
        return 0;
    }
}
