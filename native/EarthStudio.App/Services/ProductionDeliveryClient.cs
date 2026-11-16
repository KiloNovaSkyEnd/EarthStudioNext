using System.Diagnostics;
using System.Text;

namespace EarthStudio.App.Services;

sealed class ProductionDeliveryClient
{
    public async Task RunAsync(string package, string action, Action<string> report, CancellationToken cancellation)
    {
        AppPaths.RequireWritable(package);
        if (!File.Exists(Path.Combine(package,"commit.json"))) throw new ArgumentException("请选择已提交的JPG素材目录。");
        var root=AppPaths.FindEngineRoot() ?? throw new IOException("未找到Next引擎。");
        var start=new ProcessStartInfo(AppPaths.DevelopmentPython) { WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,
            RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8 };
        foreach (var arg in new[]{"-X","utf8","-u","-m","ges_next.production.package",Path.GetFullPath(package)}) start.ArgumentList.Add(arg);
        if (action=="blender") start.ArgumentList.Add("--build-blender");
        else if (action=="plan" || action=="cleanup") {
            start.ArgumentList.Add("--accept-quality");start.ArgumentList.Add(action=="plan" ? "--cleanup-plan" : "--cleanup");
        }
        else throw new ArgumentException("未知生产操作。");
        using var process=Process.Start(start) ?? throw new IOException("无法启动交付验证。");
        using var registration=cancellation.Register(() => { try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { } });
        var errors=process.StandardError.ReadToEndAsync();
        while (await process.StandardOutput.ReadLineAsync(cancellation) is { } line) report(line);
        await process.WaitForExitAsync(cancellation);
        var detail=await errors;
        await File.WriteAllTextAsync(Path.Combine(package,"delivery_last.log"),detail);
        if (process.ExitCode!=0) throw new IOException("交付校验未通过，停止清理。日志："+package);
    }
}
