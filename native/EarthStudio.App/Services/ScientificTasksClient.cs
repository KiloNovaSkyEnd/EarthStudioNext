using System.Diagnostics;
using System.Text;

namespace EarthStudio.App.Services;

sealed class ScientificTasksClient
{
    public async Task RunAsync(string root,string blender,CancellationToken cancellation)
    {
        AppPaths.RequireWritable(root);
        var packaged=File.Exists(AppPaths.ScientificEngine);
        var engineRoot=AppPaths.FindEngineRoot();
        if (!packaged && engineRoot == null) throw new InvalidOperationException("未找到科学引擎，请使用带 Engine 目录的完整发行包。");
        if (!File.Exists(blender)) throw new ArgumentException("请填写本机 Blender.exe 的完整路径。");
        var start=new ProcessStartInfo(packaged ? AppPaths.ScientificEngine : AppPaths.DevelopmentPython)
        { WorkingDirectory=packaged ? Path.GetDirectoryName(AppPaths.ScientificEngine)! : engineRoot!,
            UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,
            StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8 };
        if (!packaged) foreach(var argument in new[]{"-X","utf8","-u","-m","ges.earth_validation"}) start.ArgumentList.Add(argument);
        foreach(var argument in new[]{"native-pipeline","--root",root,"--blender",blender}) start.ArgumentList.Add(argument);
        start.Environment["PYTHONUTF8"]="1";
        var reports=Path.Combine(root,"reports"); Directory.CreateDirectory(reports);
        using var process=Process.Start(start) ?? throw new IOException("无法启动处理引擎。");
        using var registration=cancellation.Register(()=>{ try { process.Kill(true); } catch(InvalidOperationException){} });
        var stdout=process.StandardOutput.ReadToEndAsync(); var stderr=process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync(cancellation);
        var tag=DateTime.UtcNow.ToString("yyyyMMddTHHmmssZ");
        await File.WriteAllTextAsync(Path.Combine(reports,$"desktop_pipeline_{tag}.log"),await stdout);
        await File.WriteAllTextAsync(Path.Combine(reports,$"desktop_pipeline_{tag}.err.log"),await stderr);
        cancellation.ThrowIfCancellationRequested();
        if (process.ExitCode!=0) throw new InvalidOperationException("任务失败或已有同一项目任务运行；详情见测试目录 reports，已完成素材保留。");
    }
}
