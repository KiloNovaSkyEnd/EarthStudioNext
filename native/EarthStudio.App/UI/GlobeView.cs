using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.Web.WebView2.Core;

namespace EarthStudio.App.UI;

sealed class GlobeView
{
    public Grid Content { get; } = new();
    private readonly WebView2 web = new();
    private readonly TextBlock fallback = Ui.Text("正在初始化三维预览…", 16, true);
    public bool Ready { get; private set; }
    private object? pendingWeather;
    private string? weatherFolder;
    private string? activeFolder;
    private bool initialized;
    public GlobeView()
    {
        Content.Children.Add(fallback);
        Content.Children.Add(web);
        web.Loaded += async (_, _) =>
        {
            try
            {
                await web.EnsureCoreWebView2Async();
                web.CoreWebView2.SetVirtualHostNameToFolderMapping("earth.local",
                    Path.Combine(AppContext.BaseDirectory, "Preview"), CoreWebView2HostResourceAccessKind.DenyCors);
                web.CoreWebView2.Settings.AreDevToolsEnabled = false;
                web.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
                web.CoreWebView2.NavigationStarting += (_, args) =>
                { if (!args.Uri.StartsWith("https://earth.local/", StringComparison.Ordinal)) args.Cancel = true; };
                web.CoreWebView2.WebMessageReceived += (_, args) =>
                {
                    using var doc = JsonDocument.Parse(args.WebMessageAsJson);
                    Ready = doc.RootElement.TryGetProperty("ready", out var ready) && ready.GetBoolean();
                    if (Ready && pendingWeather != null) SendWeather();
                };
                initialized=true;
                if (weatherFolder != null) NavigateWeather();
                else web.Source = new Uri("https://earth.local/index.html");
            }
            catch { web.Visibility = Visibility.Collapsed; fallback.Text = "三维预览不可用，请检查 WebView2 Runtime。项目与目录检查仍可使用。"; }
        };
    }
    public void SetTime(DateTimeOffset time)
    {
        if (web.CoreWebView2 != null)
            web.CoreWebView2.PostWebMessageAsJson(JsonSerializer.Serialize(new { time = time.ToString("yyyy-MM-dd HH:mm 'UTC'") }));
    }
    public void SetWeather(string folder, string filename, string utc,double[]? sun=null,bool atmosphere=true)
    {
        if (Path.GetFileName(filename) != filename || !filename.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("天气预览文件名无效。");
        weatherFolder=Path.GetFullPath(folder);
        pendingWeather = new { weather = "https://legacy-materials.local/" + Uri.EscapeDataString(filename)+"?v="+DateTime.UtcNow.Ticks, time = utc, sun, atmosphere };
        if (initialized)
        {
            if (activeFolder != weatherFolder) NavigateWeather();
            else if (Ready) SendWeather();
        }
    }
    private void NavigateWeather()
    {
        // Historical diagnostics remain read-only, including protected archives.
        Ready=false; activeFolder=weatherFolder;
        web.CoreWebView2.SetVirtualHostNameToFolderMapping("legacy-materials.local",weatherFolder!,CoreWebView2HostResourceAccessKind.Allow);
        web.Source=new Uri("https://earth.local/index.html?v="+DateTime.UtcNow.Ticks);
    }
    private void SendWeather()
    {
        web.CoreWebView2.PostWebMessageAsJson(JsonSerializer.Serialize(pendingWeather));
    }
}
