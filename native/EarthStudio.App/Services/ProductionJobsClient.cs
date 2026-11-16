using System.Diagnostics;
using System.Text;
using EarthStudio.Core;

namespace EarthStudio.App.Services;

sealed class ProductionJobsClient
{
    public async Task<string> RunAsync(EarthProject project, string utc, Action<string> progress, CancellationToken cancellation)
    {
        var options = project.Production;
        options.Validate();
        project.SatelliteSelection.Validate();
        if (project.SatelliteSelection.Mode!="manual" || !project.SatelliteSelection.Satellites.SequenceEqual(new[]{"himawari9"}))
            throw new ArgumentException("本批JPG生产只接入向日葵9号。请先选择“仅向日葵9号”；不会忽略卫星选择制作其他数据。");
        if (options.Format != "jpeg" || options.HimawariDiskSize != 11000 || options.NightLightMetres is not (500 or 1000))
            throw new ArgumentException("本批生产试运行支持H9 11K JPG＋500m/1km夜景。其他档位保留设置，待各自接入验证。");
        if (!DateTimeOffset.TryParse(utc, out var stamp) || stamp.Offset != TimeSpan.Zero || stamp.Second != 0 || stamp.Minute % 10 != 0)
            throw new ArgumentException("请输入准确的UTC十分钟时次，例如2026-10-20T13:00:00Z。");
        var root = AppPaths.FindEngineRoot() ?? throw new IOException("未找到Next引擎。");
        var source = Path.Combine(root, "data/projects/H9_20261020_UTCminus7_1100_1700");
        var reference = AppPaths.FindAuxiliaryReferenceRoot();
        var output = Path.Combine(root, "data/production_jobs", $"Desktop_{stamp:yyyyMMddTHHmmZ}_{Guid.NewGuid():N}");
        AppPaths.RequireWritable(output);
        var start = new ProcessStartInfo(AppPaths.DevelopmentPython) { WorkingDirectory = root, UseShellExecute = false,
            CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
        foreach (var arg in new[] { "-X", "utf8", "-u", "-m", "ges_next.production", "--source-root", source,
            "--reference", reference, "--utc", stamp.UtcDateTime.ToString("yyyy-MM-ddTHH:mm:ssZ"), "--output", output,
            "--quality", options.JpegQuality.ToString(), "--night-metres", options.NightLightMetres.ToString() }) start.ArgumentList.Add(arg);
        if (options.KeepL1) start.ArgumentList.Add("--keep-l1");
        if (options.KeepIntermediates) start.ArgumentList.Add("--keep-intermediates");
        using var process = Process.Start(start) ?? throw new IOException("无法启动素材生产。");
        using var registration = cancellation.Register(() => { try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { } });
        var errors = process.StandardError.ReadToEndAsync();
        while (await process.StandardOutput.ReadLineAsync(cancellation) is { } line) progress(line);
        await process.WaitForExitAsync(cancellation);
        Directory.CreateDirectory(output);
        await File.WriteAllTextAsync(Path.Combine(output, "engine_stderr.log"), await errors);
        if (process.ExitCode != 0 || !File.Exists(Path.Combine(output, "commit.json"))) throw new IOException("生产未提交，输入保留；日志：" + output);
        return output;
    }
}
