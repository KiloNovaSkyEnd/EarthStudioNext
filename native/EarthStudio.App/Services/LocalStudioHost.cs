using System.Diagnostics;
using System.Text;

namespace EarthStudio.App.Services;

// Owns one loopback renderer host; never reuses/kills another application's port.
sealed class LocalStudioHost : IDisposable
{
    private Process? process;
    private readonly StringBuilder errors = new();

    public async Task<Uri> StartAsync(string materials)
    {
        Dispose();
        if (!File.Exists(Path.Combine(materials, "manifest.json"))) throw new ArgumentException("目录中缺少manifest.json。");
        var root = AppPaths.FindEngineRoot() ?? throw new InvalidOperationException("当前开发版需要Next科学引擎目录。");
        var python = AppPaths.DevelopmentPython;
        if (!File.Exists(python)) throw new FileNotFoundException("未找到本机科学运行环境。", python);
        var start = new ProcessStartInfo(python) { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
        foreach (var arg in new[] { "-X", "utf8", "-u", Path.Combine(AppContext.BaseDirectory,"Cesium","preview_host.py"), "--engine", root, "--music", Path.Combine(AppPaths.UserData,"MusicAssets"), "--materials", materials, "--port", "0" }) start.ArgumentList.Add(arg);
        var renderer = Path.Combine(AppContext.BaseDirectory, "Cesium");
        if (File.Exists(Path.Combine(renderer, "index.html"))) { start.ArgumentList.Add("--ui"); start.ArgumentList.Add(renderer); }
        var ready = new TaskCompletionSource<Uri>(TaskCreationOptions.RunContinuationsAsynchronously);
        process = new Process { StartInfo = start, EnableRaisingEvents = true };
        process.OutputDataReceived += (_, e) =>
        {
            if (Uri.TryCreate(e.Data, UriKind.Absolute, out var uri) && uri.Scheme == "http" && uri.Host == "127.0.0.1") ready.TrySetResult(uri);
        };
        process.ErrorDataReceived += (_, e) => { if (e.Data != null) lock (errors) { errors.AppendLine(e.Data); if (errors.Length > 8192) errors.Remove(0, errors.Length - 8192); } };
        process.Exited += (_, _) => ready.TrySetException(new IOException("本地素材服务已退出。"));
        try
        {
            process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
            return await ready.Task.WaitAsync(TimeSpan.FromSeconds(30));
        }
        catch { Dispose(); throw; }
    }

    public void Dispose()
    {
        if (process == null) return;
        try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { }
        process.Dispose(); process = null;
    }
}
