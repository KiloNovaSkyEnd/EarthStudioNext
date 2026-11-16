using EarthStudio.Core;
using EarthStudio.App.Services;
using EarthStudio.App.UI;
using System.Text.Json;

namespace EarthStudio.App;

sealed partial class MainWindow
{
    private readonly PipelineView pipeline=new();
    private readonly PipelineClient queues=new();
    private string? lastInventory;
    private async Task<string?> PrepareSequenceWithStorageAsync(string? artistBlend=null)
    {
        JsonElement estimate=default;
        status.Text="正在预检素材占用；尚未复制图像…";
        await RunPipelineTask(async token=>estimate=await queues.EstimateStorageAsync(token));
        double Gb(string name)=>estimate.GetProperty(name).GetInt64()/1073741824.0;
        var reusable=artistBlend==null?estimate.GetProperty("reusable").GetString():null;
        var budget=Gb("preview_budget_bytes");var full=Gb("copy_bytes");var free=Gb("free_bytes");
        var text=$"{estimate.GetProperty("observations").GetInt32()}个真实观测，正式图层约{full:F1} GB。\n本机编辑：共用已有图层，不复制11K大图；预览及临时文件预留预算约{budget:F1} GB，实际通常更少。\n独立打包：额外复制约{full:F1} GB图层，再加预览预算。\n目标盘剩余{free:F1} GB。共享图层请勿在外部软件原地覆盖。";
        if(reusable!=null)text="已找到相同时间范围的现有成果，直接打开不再制作副本。\n\n"+text;
        var dialog=new Microsoft.UI.Xaml.Controls.ContentDialog{XamlRoot=((Microsoft.UI.Xaml.FrameworkElement)Content).XamlRoot,Title="素材准备与硬盘占用",Content=text,
            PrimaryButtonText=reusable!=null?"打开已有成果（不复制）":"本机编辑（共用大图）",SecondaryButtonText="独立打包（复制大图）",CloseButtonText="取消",
            DefaultButton=Microsoft.UI.Xaml.Controls.ContentDialogButton.Primary,IsPrimaryButtonEnabled=reusable!=null||free>=budget,IsSecondaryButtonEnabled=free>=full+budget};
        var choice=await dialog.ShowAsync();
        if(choice==Microsoft.UI.Xaml.Controls.ContentDialogResult.None)return null;
        if(choice==Microsoft.UI.Xaml.Controls.ContentDialogResult.Primary&&reusable!=null)return reusable;
        var storage=choice==Microsoft.UI.Xaml.Controls.ContentDialogResult.Secondary?"copy":"local";
        string? output=null;
        await RunPipelineTask(async token=>output=await queues.AssembleAsync(ReceivePipeline,token,artistBlend,storage));
        return output;
    }
    private void ConfigurePipeline()
    {
        pipeline.CancelRangeRequested+=(first,last)=>Guard(async()=>
        {
            await RunPipelineTask(token=>queues.CancelRangeAsync(first,last,ReceivePipeline,token));
            status.Text="已登记取消范围；已完成和已经开始的时次保留，后台在调度边界接收。";
        });
        void ApplyConcurrency()=>queues.ConfigureExecution(pipeline.Concurrency.Parallel,pipeline.Concurrency.Control,pipeline.Concurrency.Target,pipeline.Concurrency.Prefetch,
            pipeline.Concurrency.VerificationMode,pipeline.Concurrency.SampleInterval);
        pipeline.Concurrency.ApplyRequested+=()=>Guard(async()=>{ApplyConcurrency();status.Text="并行设置已保存。支持动态调度的后台约10秒内生效；已开始的时次正常完成。串行后台需下次继续时应用。";await Task.CompletedTask;});
        pipeline.UpdateBlenderRequested+=()=>Guard(async()=>
        {
            if(running!=null || background.IsActive(BackgroundLane.Production))throw new InvalidOperationException("请先完成当前制作任务。");
            var source=await pickers.OpenBlenderAsync();if(source==null)return;
            var output=await PrepareSequenceWithStorageAsync(source);
            if(output!=null){pipeline.SetDelivery(output);project.SetMaterialsDirectory(output);await SaveWorkingProjectAsync();}
        });
        pipeline.ReuseRequested+=()=>Guard(async()=>
        {
            var value=project.ReadProject();
            if(queues.QueueDirectory!=null)throw new ArgumentException("请在尚未生成队列的新项目中选择复用来源，已有队列请使用追加。");
            if(lastInventory==null || inventoryProject==null || !WorkflowRules.SameProduction(value,inventoryProject))throw new ArgumentException("请先按本项目日期完成第3步目录检查。");
            if(WorkflowRules.ProductionBlocker(value) is {} blocker)throw new ArgumentException(blocker);
            var sourceFile=await pickers.OpenProjectAsync();if(sourceFile==null)return;
            var sourceProject=await store.LoadAsync(sourceFile);
            var source=sourceProject.PipelineDirectory;
            if(string.IsNullOrWhiteSpace(source))throw new ArgumentException("所选项目未保存制作队列，请先在源项目保存已完成的队列。");
            using(var sourcePlan=JsonDocument.Parse(AtomicJsonFile.Read(Path.Combine(source,"plan.json"))))
            {
                var owner=sourcePlan.RootElement.GetProperty("project").GetProperty("Id").GetString();
                if(!Guid.TryParse(owner,out var sourceId) || sourceId!=sourceProject.Id)throw new ArgumentException("源项目与其制作队列不匹配，请重新保存正确项目。");
            }
            await RunPipelineTask(async token=>
            {
                await queues.PlanAsync(value,lastInventory,ReceivePipeline,token,reuseSource:source);
                project.SetPipelineDirectory(queues.QueueDirectory!);await SaveWorkingProjectAsync();
                status.Text="跨项目复用计划已生成；重叠时次已完成，只需开始制作新增时次。源素材目录须保留。";
            });
        });
        pipeline.AppendRequested+=()=>Guard(async()=>
        {
            var value=project.ReadProject();
            if(lastInventory==null || inventoryProject==null || !EarthStudio.Core.WorkflowRules.SameProduction(value,inventoryProject))throw new ArgumentException("先按延长后的日期完成目录检查，再生成追加计划。");
            if(queues.QueueDirectory==null)throw new ArgumentException("请先打开本项目原来已完成的制作队列。");
            await RunPipelineTask(async token=>
            {
                await queues.PlanAsync(value,lastInventory,ReceivePipeline,token,append:true);
                project.SetPipelineDirectory(queues.QueueDirectory!);await SaveWorkingProjectAsync();
                status.Text="追加范围已登记到原队列；暂停状态保留，运行中的后台自动接收。";
            });
        });
        pipeline.NightRequested+=path=>Guard(()=>RunAsync(new {action="configure-night",options=new {path}}));
        pipeline.NightStatusRequested+=()=>Guard(()=>RunAsync(new {action="night-status"}));
        pipeline.PlanRequested+=()=>Guard(async()=> {
            var value=project.ReadProject();
            if(lastInventory==null || inventoryProject==null || !EarthStudio.Core.WorkflowRules.SameProduction(value,inventoryProject))throw new ArgumentException("请先完成第3步数据检查；已有暂停队列可直接打开。");
            if(EarthStudio.Core.WorkflowRules.ProductionBlocker(value) is {} blocker)throw new ArgumentException(blocker);
            await RunPipelineTask(async token=> {
                var preserve=queues.QueueDirectory!=null && queues.Read("state.json").GetProperty("completed").GetArrayLength()>0;
                await queues.PlanAsync(value,lastInventory,ReceivePipeline,token,append:preserve);
                project.SetPipelineDirectory(queues.QueueDirectory!);
                await SaveWorkingProjectAsync();
            });
        });
        pipeline.RunRequested+=(accepted,allowMissing)=>Guard(async()=>
        {
            if(queues.QueueDirectory!=null && QueueMonitor.Read(queues.QueueDirectory).Active){PollQueue();return;}
            ApplyConcurrency();
            await RunPipelineTask(token=>queues.RunAsync(project.ReadProject(),accepted,allowMissing,ReceivePipeline,token),production:true);
        });
        pipeline.FolderRequested+=()=>Guard(async()=> {
            if(running!=null || background.IsActive(BackgroundLane.Production) || background.IsActive(BackgroundLane.Catalog) || background.IsActive(BackgroundLane.QueueEdit))throw new InvalidOperationException("请先完成当前操作再切换制作队列；当前项目可以直接追加范围。");
            var path=await pickers.FolderAsync();if(path==null)return;
            queues.Attach(path);
            var frozen=queues.Read("plan.json").GetProperty("project").Deserialize<EarthStudio.Core.EarthProject>() ?? throw new ArgumentException("队列没有项目设置。");
            frozen.Validate(DateTimeOffset.UtcNow);
            if(project.ReadProject().Id!=frozen.Id){projectFile=null;cesium.Clear();}
            project.SetProject(frozen with {PipelineDirectory=path});cesium.ProjectId=frozen.Id;
            await SaveWorkingProjectAsync();RefreshPipeline();RefreshWorkflow();
        });
        pipeline.PauseRequested+=()=>{if(!queues.RequestSafePause())background.Cancel(BackgroundLane.Production);else {queuePausePending=true;PollQueue();status.Text="已请求安全暂停；当前已开始的时次完成校验与清理后停下。";}};
        pipeline.ImmediatePauseRequested+=()=>background.Cancel(BackgroundLane.Production);
        pipeline.SequenceRequested+=()=>Guard(async()=> {
            var output=await PrepareSequenceWithStorageAsync();
            if(output!=null){pipeline.SetDelivery(output);project.SetMaterialsDirectory(output);await SaveWorkingProjectAsync();SelectPage("cesium");await cesium.SetFolderAsync(output);}
        });
        StartQueueMonitor();
    }
    private void ReceivePipeline(JsonElement value)
    {
        var copy=value.Clone();DispatcherQueue.TryEnqueue(()=>pipeline.Accept(copy));
    }
    private void RefreshPipeline()
    {
        if(queues.QueueDirectory==null)return;
        pipeline.Bind(queues.Read("plan.json"));pipeline.Accept(queues.Read("state.json"));
        if(File.Exists(Path.Combine(queues.QueueDirectory,"unattended.json")))
        {
            var policy=queues.Read("unattended.json");
            if(policy.TryGetProperty("last_allow_missing",out var allow))pipeline.LoadMissingDecision(allow.GetBoolean());
        }
        var file=Path.Combine(queues.QueueDirectory,"execution.json");
        if(File.Exists(file))
        {
            var value=queues.Read("execution.json");
            pipeline.Concurrency.Load(value.TryGetProperty("control",out var control)?control.GetString()??"auto":"auto",
                value.TryGetProperty("max_compute",out var maximum)?maximum.GetInt32():8,
                value.TryGetProperty("prefetch",out var ahead)?ahead.GetInt32():3,
                value.GetProperty("mode").GetString()=="parallel");
            pipeline.Concurrency.LoadVerification(value.TryGetProperty("verification",out var verification)?verification.GetProperty("mode").GetString()??"strict":"strict",
                value.TryGetProperty("verification",out var policy)&&policy.TryGetProperty("sample_interval",out var interval)?interval.GetInt32():50);
        }
        PollQueue();
    }
    private void ClearPipeline(){queuePausePending=false;lastInventory=null;inventoryProject=null;queues.Clear();pipeline.Clear();tasks.Reset();}
    private async Task RunPipelineTask(Func<CancellationToken,Task> action,bool production=false)
    {
        var operation=background.Begin(production?BackgroundLane.Production:BackgroundLane.QueueEdit);
        RefreshCancelButton();pipeline.SetBusy(true,background.IsActive(BackgroundLane.Production));bool paused=false;
        try {await action(operation.Token);}
        catch(OperationCanceledException){paused=production;throw;}
        finally {
            operation.Dispose();RefreshCancelButton();pipeline.SetBusy(background.IsActive(BackgroundLane.Production)||background.IsActive(BackgroundLane.QueueEdit),background.IsActive(BackgroundLane.Production));
            RefreshPipeline();RefreshWorkflow();if(paused)pipeline.Paused();
        }
    }
}
