using Microsoft.UI.Xaml;

namespace EarthStudio.App;

internal static class Program
{
    [STAThread]
    static void Main()
    {
        var localAppData = Environment.GetEnvironmentVariable("EARTHSTUDIO_LOCALAPPDATA");
        if (!string.IsNullOrWhiteSpace(localAppData))
            Environment.SetEnvironmentVariable("LOCALAPPDATA", localAppData);
        Environment.SetEnvironmentVariable("EARTHSTUDIO_BLENDER", AppPaths.BlenderExecutable);
        Directory.CreateDirectory(AppPaths.UserData);
        Environment.SetEnvironmentVariable("WEBVIEW2_USER_DATA_FOLDER", Path.Combine(AppPaths.UserData, "WebView"));
        File.AppendAllText(Path.Combine(AppPaths.UserData, "startup.log"), "Starting " + DateTimeOffset.UtcNow.ToString("O") + "\n");
        WinRT.ComWrappersSupport.InitializeComWrappers();
        Application.Start(parameters =>
        {
            File.AppendAllText(Path.Combine(AppPaths.UserData, "startup.log"), "Application callback\n");
            SynchronizationContext.SetSynchronizationContext(
                new Microsoft.UI.Dispatching.DispatcherQueueSynchronizationContext(
                    Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread()));
            _ = new StudioApplication();
        });
    }
}

sealed partial class StudioApplication : Application
{
    private MainWindow? window;
    public StudioApplication()
    {
        File.AppendAllText(Path.Combine(AppPaths.UserData, "startup.log"), "Application constructor\n");
        UnhandledException += (_, e) =>
        {
            Directory.CreateDirectory(AppPaths.UserData);
            File.AppendAllText(Path.Combine(AppPaths.UserData, "errors.log"),
                $"{DateTimeOffset.UtcNow:O} {e.Exception}\n");
        };
        InitializeComponent();
    }
    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        try
        {
            File.AppendAllText(Path.Combine(AppPaths.UserData, "startup.log"), "Constructing window\n");
            window = new MainWindow();
            File.AppendAllText(Path.Combine(AppPaths.UserData, "startup.log"), "Activating window\n");
            window.Activate();
        }
        catch (Exception e)
        {
            File.AppendAllText(Path.Combine(AppPaths.UserData, "errors.log"), e.ToString() + "\n");
            throw;
        }
    }
}
