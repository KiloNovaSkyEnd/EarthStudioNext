using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace EarthStudio.App.Services;

sealed class EngineClient
{
    public bool IsAvailable => File.Exists(AppPaths.ScientificEngine) || Root != null && File.Exists(Python);
    private string? Root => AppPaths.FindEngineRoot();
    private string Python => AppPaths.DevelopmentPython;

    public async Task RunAsync(object request, Action<JsonElement> received, CancellationToken cancellation)
    {
        if (!IsAvailable) throw new InvalidOperationException("未找到配套卫星引擎。请从完整发行目录运行；当前开发版需项目内 .venv。");
        var packaged=File.Exists(AppPaths.ScientificEngine);
        var start = new ProcessStartInfo(packaged ? AppPaths.ScientificEngine : Python)
        {
            WorkingDirectory = packaged ? Path.GetDirectoryName(AppPaths.ScientificEngine)! : Root!, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8
        };
        if (packaged) start.ArgumentList.Add("bridge");
        else { start.ArgumentList.Add("-u"); start.ArgumentList.Add("-m"); start.ArgumentList.Add("ges_next.bridge"); }
        start.Environment["PYTHONUTF8"] = "1";
        cancellation.ThrowIfCancellationRequested();
        using var process = Process.Start(start) ?? throw new InvalidOperationException("无法启动卫星引擎。");
        using var registration = cancellation.Register(() => { try { process.Kill(true); } catch (InvalidOperationException) { } });
        try
        {
        // Secrets are piped in memory, never recorded in arguments or task manifests.
        await process.StandardInput.WriteAsync(JsonSerializer.Serialize(request));
        process.StandardInput.Close();
        var errors = process.StandardError.ReadToEndAsync();
        var failed = false;
        while (await process.StandardOutput.ReadLineAsync(cancellation) is { } line)
        {
            using var document = JsonDocument.Parse(line);
            var message = document.RootElement.Clone();
            failed |= message.GetProperty("type").GetString() == "error";
            received(message);
        }
        await process.WaitForExitAsync(cancellation);
        _ = await errors; // Never surface library stderr that might contain authentication URLs.
        cancellation.ThrowIfCancellationRequested();
        if (process.ExitCode != 0 && !failed) throw new InvalidOperationException("卫星引擎退出异常；已完成记录保留。");
        }
        catch(Exception) when(cancellation.IsCancellationRequested)
        {
            throw new OperationCanceledException(cancellation);
        }
        finally
        {
            if(!process.HasExited)
            {
                process.Kill(true);
                await process.WaitForExitAsync();
            }
        }
    }
}
