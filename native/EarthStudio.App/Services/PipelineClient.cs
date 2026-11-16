using System.Diagnostics;
using System.Text;
using System.Text.Json;
using EarthStudio.Core;

namespace EarthStudio.App.Services;

sealed class PipelineClient
{
    public string? QueueDirectory { get; private set; }
    public void Clear() => QueueDirectory=null;
    public void ConfigureExecution(bool parallel,string control,int maximum,int prefetch,string? verificationMode=null,int sampleInterval=50)
    {
        if(QueueDirectory==null)throw new ArgumentException("请先生成或打开队列。");
        if(maximum<1||maximum>8||prefetch<1||prefetch>8)throw new ArgumentException("并行与预取数量必须为1–8。");
        var file=Path.Combine(QueueDirectory,"execution.json");
        var settings=new Dictionary<string,object?>();
        if(File.Exists(file))
        {
            using var current=JsonDocument.Parse(AtomicJsonFile.Read(file));
            foreach(var property in current.RootElement.EnumerateObject())settings[property.Name]=property.Value.Clone();
        }
        settings["mode"]=parallel?"parallel":"serial";settings["control"]=control;settings["max_compute"]=maximum;settings["prefetch"]=prefetch;
        if(verificationMode!=null)
        {
            if(verificationMode is not ("strict" or "batch") || sampleInterval<1 || sampleInterval>100)
                throw new ArgumentException("校验方式无效，抽检间隔请输入1–100帧。");
            settings["verification"]=new {mode=verificationMode,sample_interval=sampleInterval};
        }
        AtomicJsonFile.Write(file,JsonSerializer.Serialize(settings));
    }
    public bool RequestSafePause()
    {
        if(QueueDirectory==null)return false;
        var execution=Path.Combine(QueueDirectory,"execution.json");
        if(!File.Exists(execution))return false;
        using var document=JsonDocument.Parse(AtomicJsonFile.Read(execution));
        var state=Read("state.json");
        if(document.RootElement.GetProperty("mode").GetString()!="parallel" &&
            (!state.TryGetProperty("phase",out var phase)||phase.GetString() is not ("parallel-running" or "parallel-progress")))return false;
        AtomicJsonFile.Write(Path.Combine(QueueDirectory,"pause_requested.json"),JsonSerializer.Serialize(new {requested_utc=DateTimeOffset.UtcNow}));
        return true;
    }
    public JsonElement Read(string name)
    {
        if(QueueDirectory==null)throw new ArgumentException("请先生成或打开制作队列。");
        var file=Path.Combine(QueueDirectory,name);
        if(name=="plan.json" && File.Exists(Path.Combine(QueueDirectory,"effective_plan_summary.json")))file=Path.Combine(QueueDirectory,"effective_plan_summary.json");
        using var document=JsonDocument.Parse(AtomicJsonFile.Read(file));
        return document.RootElement.Clone();
    }
    public void Attach(string path)
    {
        AppPaths.RequireWritable(path);
        foreach(var file in new[]{"plan.json","state.json"})if(!File.Exists(Path.Combine(path,file)))throw new ArgumentException("此目录没有有效队列。");
        QueueDirectory=Path.GetFullPath(path);
    }
    public async Task PlanAsync(EarthProject project,string inventory,Action<JsonElement> report,CancellationToken cancellation,bool append=false,string? reuseSource=null)
    {
        var output=ReadableNames.AvailablePath(Path.Combine(project.DataDirectory,"projects",project.Id.ToString("N"),"queues"),$"制作队列_{DateTime.UtcNow:yyyy-MM-dd_HH-mm-ss}_UTC");
        AppPaths.RequireWritable(output);
        var request=Path.Combine(AppPaths.UserData,"PipelineRequests",Guid.NewGuid().ToString("N")+".json");
        await new ProjectStore().SaveAsync(request,project);
        if(append && QueueDirectory!=null)
        {
            await ExecuteAsync("revise",QueueDirectory,request,inventory,false,report,cancellation);
            return;
        }
        await ExecuteAsync("plan",output,request,inventory,false,report,cancellation,append?QueueDirectory:null,reuseSource);
        Attach(output);
    }
    public async Task CancelRangeAsync(string first,string last,Action<JsonElement> report,CancellationToken cancellation)
    {
        if(QueueDirectory==null)throw new ArgumentException("请先打开本项目队列。");
        if(!DateTimeOffset.TryParse(first,out _)||!DateTimeOffset.TryParse(last,out _))throw new ArgumentException("请输入带Z或时区偏移的完整UTC时间。");
        var root=AppPaths.FindEngineRoot()??throw new IOException("未找到Next引擎。");
        var start=new ProcessStartInfo(AppPaths.DevelopmentPython){WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8};
        foreach(var arg in new[]{"-X","utf8","-u","-m","ges_next.pipeline.queue_changes","--queue",QueueDirectory,"--cancel-start",first,"--cancel-end",last})start.ArgumentList.Add(arg);
        await PipelineWorkerSupervisor.RunAsync(start,"cancel-range",QueueDirectory,report,cancellation);
    }
    public async Task RunAsync(EarthProject project,bool accepted,bool allowMissing,Action<JsonElement> report,CancellationToken cancellation)
    {
        if(QueueDirectory==null)throw new ArgumentException("请先生成制作计划。");
        var request=Path.Combine(QueueDirectory,"current_request.earthproj");
        await new ProjectStore().SaveAsync(request,project);
        await ExecuteAsync(accepted?"accept":"run",QueueDirectory,request,null,allowMissing,report,cancellation);
    }
    public async Task<JsonElement> EstimateStorageAsync(CancellationToken cancellation)
    {
        if(QueueDirectory==null)throw new ArgumentException("请先打开制作队列。");
        var root=AppPaths.FindEngineRoot()??throw new IOException("未找到Next引擎。");
        var start=new ProcessStartInfo(AppPaths.DevelopmentPython){WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8};
        foreach(var arg in new[]{"-X","utf8",Path.Combine(root,"reports","local_edit_storage_20261029","estimate.py"),QueueDirectory})start.ArgumentList.Add(arg);
        using var process=Process.Start(start)??throw new IOException("无法检查素材占用。");
        using var registration=cancellation.Register(()=>{try{if(!process.HasExited)process.Kill(true);}catch(InvalidOperationException){}});
        var output=process.StandardOutput.ReadToEndAsync(cancellation);var errors=process.StandardError.ReadToEndAsync(cancellation);
        await process.WaitForExitAsync(cancellation);var text=await output;var error=await errors;
        if(process.ExitCode!=0)throw new IOException("空间预检失败，未复制素材："+error);
        using var json=JsonDocument.Parse(text);return json.RootElement.Clone();
    }
    public async Task<string> AssembleAsync(Action<JsonElement> report,CancellationToken cancellation,string? artistBlend=null,string storage="local")
    {
        if(QueueDirectory==null)throw new ArgumentException("请先打开制作队列。");
        var saved=Read("plan.json").GetProperty("project").Deserialize<EarthProject>() ?? throw new ArgumentException("队列缺少项目设置。");
        var output=ReadableNames.AvailablePath(Path.Combine(saved.DataDirectory,"素材交付"),"素材_"+ReadableNames.ProjectLabel(saved));
        var root=AppPaths.FindEngineRoot()??throw new IOException("未找到Next引擎。");
        var start=new ProcessStartInfo(AppPaths.DevelopmentPython){WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8};
        foreach(var arg in new[]{"-X","utf8","-u",Path.Combine(root,"reports","local_edit_storage_20261029","prepare.py"),"--queue",QueueDirectory,"--output",output,"--storage",storage})start.ArgumentList.Add(arg);
        if(artistBlend!=null){start.ArgumentList.Add("--update-blend");start.ArgumentList.Add(artistBlend);}
        using var process=Process.Start(start)??throw new IOException("无法启动序列准备。");
        using var registration=cancellation.Register(()=>{try{if(!process.HasExited)process.Kill(true);}catch(InvalidOperationException){}});
        var errors=process.StandardError.ReadToEndAsync();
        string? failure=null;
        while(await process.StandardOutput.ReadLineAsync(cancellation) is {} line)
        {
            using var json=JsonDocument.Parse(line);var value=json.RootElement;
            if(value.TryGetProperty("error",out var error)&&value.TryGetProperty("phase",out var phase)&&phase.GetString() is "error" or "failed-inputs-preserved")failure=error.GetString();
            report(value.Clone());
        }
        await process.WaitForExitAsync(cancellation);var stderr=await errors;
        if(Directory.Exists(output))await File.WriteAllTextAsync(Path.Combine(output,"assembly.log"),stderr);
        if(process.ExitCode!=0)throw new IOException("素材序列准备失败，旧结果保留："+(failure??output));
        return output;
    }
    private static async Task ExecuteAsync(string action,string output,string project,string? inventory,bool allowMissing,Action<JsonElement> report,CancellationToken cancellation,string? previous=null,string? reuseSource=null)
    {
        var root=AppPaths.FindEngineRoot() ?? throw new IOException("未找到Next引擎。");
        var start=new ProcessStartInfo(AppPaths.DevelopmentPython) { WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,
            RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8 };
        foreach(var arg in new[]{"-X","utf8","-u","-m","ges_next.pipeline.cli",action,"--queue",output,"--project",project})start.ArgumentList.Add(arg);
        if(inventory!=null){start.ArgumentList.Add("--inventory");start.ArgumentList.Add(inventory);}
        if(previous!=null){start.ArgumentList.Add("--previous-queue");start.ArgumentList.Add(previous);}
        if(reuseSource!=null){start.ArgumentList.Add("--reuse-source");start.ArgumentList.Add(reuseSource);}
        if(allowMissing)start.ArgumentList.Add("--allow-missing");
        await PipelineWorkerSupervisor.RunAsync(start,action,output,report,cancellation);
    }
}
