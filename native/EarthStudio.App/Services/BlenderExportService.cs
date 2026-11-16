using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace EarthStudio.App.Services;

sealed class BlenderExportService
{
    public async Task<string> ImportAsync(string cameraJson, bool high22k, CancellationToken cancellation,string? layeredFolder=null,Action<string,double?>? progress=null,string? existingBlend=null)
    {
        var root = AppPaths.FindEngineRoot() ?? throw new InvalidOperationException("未找到Next引擎。");
        var package = Path.Combine(root, "data", "exports", high22k ? "H9_20261020_12h_Blender_v1" : "H9_20261020_12h_Blender_11K_v1");
        var template = Path.Combine(package, high22k ? "Earth_Studio_动态天气与自由运镜.blend" : "Earth_Studio_11K_清晰构图版.blend");
        if(layeredFolder!=null)
        {
            if(high22k)throw new ArgumentException("当前素材是JPG分层包，不能静默替换为旧22K素材。");
            package=layeredFolder;template=Path.Combine(package,File.Exists(Path.Combine(package,"EarthStudio_JPG_单帧.blend"))?"EarthStudio_JPG_单帧.blend":"EarthStudio_JPG_动画.blend");
        }
        if(existingBlend!=null)template=existingBlend;
        var blender = FindBlender();
        var script = Path.Combine(root, "scripts", "blender_import_dynamic_cameras.py");
        foreach (var file in new[] { cameraJson, template, blender, script }) if (!File.Exists(file)) throw new FileNotFoundException("缺少Blender导出依赖。", file);
        var target = ReadableNames.AvailablePath(existingBlend==null?Path.Combine(package,"user_projects"):Path.GetDirectoryName(existingBlend)!, $"{(existingBlend==null?"Blender运镜":"更新运镜_保留外观")}_{DateTime.UtcNow:yyyy-MM-dd_HH-mm-ss}_UTC",".blend");
        AppPaths.RequireWritable(target);
        var start = new ProcessStartInfo(blender) { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
        foreach (var arg in new[] { "--background", template, "--disable-autoexec", "--python-exit-code", "1", "--python", script, "--", cameraJson, target }) start.ArgumentList.Add(arg);
        if(existingBlend!=null)start.ArgumentList.Add("--update");
        using var process = Process.Start(start) ?? throw new IOException("无法启动Blender。");
        using var registration = cancellation.Register(() => { try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { } });
        var stderr = process.StandardError.ReadToEndAsync();var output=new StringBuilder();
        var began=Stopwatch.StartNew();var stageClock=Stopwatch.StartNew();string stage="";var lastUpdate=TimeSpan.Zero;
        while(await process.StandardOutput.ReadLineAsync(cancellation) is {} line)
        {
            output.AppendLine(line);
            if(!line.StartsWith('{'))continue;
            try
            {
                using var json=JsonDocument.Parse(line);var value=json.RootElement;
                if(!value.TryGetProperty("earthstudio_progress",out _))continue;
                var next=value.GetProperty("stage").GetString()!;if(next!=stage){stage=next;stageClock.Restart();lastUpdate=TimeSpan.Zero;}
                var done=value.GetProperty("done").GetDouble();var total=value.GetProperty("total").GetDouble();
                if(began.Elapsed-lastUpdate<TimeSpan.FromMilliseconds(150)&&done<total)continue;lastUpdate=began.Elapsed;
                var fraction=total>0?Math.Clamp(done/total,0,1):0;
                var eta=done>0&&done<total&&stageClock.Elapsed.TotalSeconds>1?$" · 本阶段预计剩余{TimeSpan.FromSeconds(stageClock.Elapsed.TotalSeconds*(total-done)/done):mm\\:ss}":"";
                progress?.Invoke($"{stage} · 本阶段{fraction:P1} · 已用时{began.Elapsed:mm\\:ss}{eta}",fraction*100);
            }
            catch(JsonException) { }
        }
        await process.WaitForExitAsync(cancellation);
        var log = Path.Combine(AppPaths.UserData, "Logs", Path.GetFileNameWithoutExtension(target) + ".log");
        Directory.CreateDirectory(Path.GetDirectoryName(log)!);
        await File.WriteAllTextAsync(log, output + "\n" + await stderr);
        if (process.ExitCode != 0 || !File.Exists(target)) throw new IOException("Blender导入未完成；日志：" + log);
        await File.WriteAllTextAsync(Path.ChangeExtension(target,".camera.json"),await File.ReadAllTextAsync(cameraJson,cancellation),cancellation);
        return target;
    }

    public void Open(string path, bool high22k)
    {
        var start = new ProcessStartInfo(FindBlender()) { UseShellExecute = false };
        start.ArgumentList.Add(path); start.ArgumentList.Add("--disable-autoexec");
        if (!high22k)
        {
            var helper = Path.Combine(AppPaths.FindEngineRoot()!, "scripts", "blender_preview_modes.py");
            start.ArgumentList.Add("--python"); start.ArgumentList.Add(helper);
        }
        Process.Start(start);
    }

    private static string FindBlender()
    {
        var configured = Environment.GetEnvironmentVariable("EARTHSTUDIO_BLENDER");
        if (!string.IsNullOrWhiteSpace(configured)) return configured;
        return AppPaths.BlenderExecutable;
    }
}
