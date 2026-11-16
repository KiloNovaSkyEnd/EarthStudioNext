using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace EarthStudio.App.Services;

static class PipelineWorkerSupervisor
{
    public static async Task RunAsync(ProcessStartInfo start,string action,string output,Action<JsonElement> report,CancellationToken cancellation,Func<TimeSpan,CancellationToken,Task>? wait=null)
    {
        wait ??= (duration,token)=>Task.Delay(duration,token);
        using var power=action is "run" or "accept"?new ProductionPowerGuard():null;
        if(power!=null)report(JsonSerializer.SerializeToElement(new {phase="power-guard",active=power.Active}));
        var began=DateTime.UtcNow;var restart=0;
        while(true)
        {
            cancellation.ThrowIfCancellationRequested();
            using var process=Process.Start(start) ?? throw new IOException("无法启动制作队列。");
            using var registration=cancellation.Register(()=>{try{if(!process.HasExited)process.Kill(true);}catch(InvalidOperationException){}});
            var errors=process.StandardError.ReadToEndAsync();
            string? failure=null;
            var malformed=new StringBuilder();
            while(await process.StandardOutput.ReadLineAsync(cancellation) is {} line)
            {
                try
                {
                    using var json=JsonDocument.Parse(line);var value=json.RootElement;
                    if(value.TryGetProperty("error",out var error)&&value.TryGetProperty("phase",out var phase)&&phase.GetString() is "error" or "failed-inputs-preserved")failure=error.GetString()??"未说明的任务错误";
                    report(value.Clone());
                }
                catch(JsonException){if(malformed.Length<65536)malformed.AppendLine(line);}
            }
            await process.WaitForExitAsync(cancellation);cancellation.ThrowIfCancellationRequested();
            var stderr=await errors;
            if(Directory.Exists(output))await File.AppendAllTextAsync(Path.Combine(output,"pipeline_last.log"),$"\n[{DateTimeOffset.UtcNow:O}] exit={process.ExitCode}\n"+stderr+malformed);
            if(process.ExitCode==0)
            {
                if(malformed.Length>0)throw new IOException("后台返回无法解析的进度，请检查日志；已完成素材保留。");
                return;
            }
            if(action is not ("run" or "accept") || !PipelineRecovery.ShouldRestart(process.ExitCode,failure))
                throw new IOException("队列因错误停止，已完成素材与本时次输入保留："+(failure??"请查看队列日志。"));
            restart++;var delay=PipelineRecovery.DelaySeconds(restart);
            var recovery=new {phase="recovering-worker",attempt=restart,retry_seconds=delay,exit_code=process.ExitCode,occurred_utc=DateTimeOffset.UtcNow};
            if(PipelineRecovery.PauseRequested(output,began))
            {PipelineRecovery.Mark(output,recovery,"paused-user");return;}
            PipelineRecovery.Mark(output,recovery);report(JsonSerializer.SerializeToElement(recovery));
            for(var second=0;second<delay;second++)
            {
                await wait(TimeSpan.FromSeconds(1),cancellation);
                if(PipelineRecovery.PauseRequested(output,began))
                {PipelineRecovery.Mark(output,recovery,"paused-user");return;}
            }
        }
    }
}
