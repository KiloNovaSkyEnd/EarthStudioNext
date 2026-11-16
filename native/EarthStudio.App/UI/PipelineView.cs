using System.Diagnostics;
using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EarthStudio.App.UI;

sealed class PipelineView
{
    public UIElement Content { get; }
    public event Action<string>? NightRequested;
    private readonly TextBox nightPath=new(){Header="共享夜景参考VRT路径",PlaceholderText="可粘贴其他磁盘上的global_500m.vrt或global_1km.vrt完整路径"};
    private readonly TextBlock nightStatus=Ui.Text("尚未读取本机共享夜景参考设置。",13,true);
    public event Action? NightStatusRequested;
    public event Action? PlanRequested;
    public event Action? AppendRequested;
    public event Action? ReuseRequested;
    public event Action<string,string>? CancelRangeRequested;
    private readonly UtcDateTimePicker cancelStart=new("取消起点UTC（包含）");
    private readonly UtcDateTimePicker cancelEnd=new("取消终点UTC（包含）",new TimeSpan(23,50,0));
    private readonly TextBlock cancelRangeError=Ui.Text("",13,true);
    public event Action? UpdateBlenderRequested;
    public event Action<bool,bool>? RunRequested;
    public event Action? FolderRequested;
    public event Action? PauseRequested;
    public event Action? ImmediatePauseRequested;
    public ConcurrencyControls Concurrency {get;}=new();
    public event Action? SequenceRequested;
    private readonly TextBlock planText=Ui.Text("先完成第3步数据检查，再生成制作计划。",14,true);
    private readonly TextBlock status=Ui.Text("尚未启动下载",14);
    private readonly PipelineProgressPanel progress=new();
    private readonly CheckBox gaps=new(){Content="缺档时保留缺档标记并继续，不复制邻时次冒充观测"};
    private readonly CheckBox accepted=new(){Content="我已检查首样画质，同意同档位后续时次按设置自动校验与清理",Visibility=Visibility.Collapsed};
    private readonly Button reuse,plan,start,approve,open,pause,immediatePause,folder,sequence;
    private bool busy,ownedProduction,hasPlan,needsQuality,canPlan,queueMatches=true,hasReadable;
    private bool externalActive,activityKnown=true,pausePending;
    private string currentPhase="";
    private readonly TextBlock connection=Ui.Text("",13,true);
    private readonly TextBlock readiness=Ui.Text("先完成第3步目录检查。",13,true);
    private int total,completedCount;
    private string? sample,delivery;
    private readonly TextBlock deliveryText=Ui.Text("交付后可在这里打开图片、素材目录与Blender工程。",13,true);
    private readonly Button browseDelivery,openDeliveryBlend;
    public PipelineView()
    {
        plan=Ui.Button("生成 / 更新制作计划（不下载）",()=>PlanRequested?.Invoke(),true);
        reuse=Ui.Button("从已完成项目复用重叠时段（选择项目文件）",()=>ReuseRequested?.Invoke());
        start=Ui.Button("开始 / 继续下载与制作",()=>RunRequested?.Invoke(false,gaps.IsChecked==true),true);
        approve=Ui.Button("首样验收通过，继续队列",()=>RunRequested?.Invoke(true,gaps.IsChecked==true),true);
        open=Ui.Button("打开首个Blender样本",OpenSample);
        pause=Ui.Button("安全暂停（完成当前批）",()=>PauseRequested?.Invoke());
        immediatePause=Ui.Button("立即暂停（保留当前输入）",()=>ImmediatePauseRequested?.Invoke());
        folder=Ui.Button("打开已有队列",()=>FolderRequested?.Invoke());
        sequence=Ui.Button("打开已完成区间 → 运镜与Blender",()=>SequenceRequested?.Invoke(),true);
        browseDelivery=Ui.Button("打开交付成果目录",()=>{if(delivery!=null)Process.Start(new ProcessStartInfo(delivery){UseShellExecute=true});});
        openDeliveryBlend=Ui.Button("打开交付的Blender工程",()=>
        {
            if(delivery==null)return;
            var names=new[]{"EarthStudio_保留编辑_更新天气.blend","EarthStudio_JPG_动画.blend","EarthStudio_JPG_单帧.blend"};
            var file=names.Select(n=>Path.Combine(delivery,n)).FirstOrDefault(File.Exists);
            if(file==null){status.Text="Blender工程尚未完成，请查看交付目录和日志。";return;}
            new EarthStudio.App.Services.BlenderExportService().Open(file,false);
        });
        browseDelivery.IsEnabled=false;
        // Progress text varies from a short heartbeat to many active scans.
        // Give it its own fixed viewport so it cannot move settings or buttons.
        var progressViewport=new ScrollViewer
        {
            Content=status,Height=240,
            VerticalScrollBarVisibility=ScrollBarVisibility.Visible,
            HorizontalScrollBarVisibility=ScrollBarVisibility.Disabled,
            HorizontalScrollMode=ScrollMode.Disabled
        };
        Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(progressViewport,"制作进度");
        connection.Height=36;connection.MaxLines=2;connection.TextTrimming=TextTrimming.CharacterEllipsis;
        accepted.Checked+=(_,_)=>UpdateButtons();accepted.Unchecked+=(_,_)=>UpdateButtons();
        Content=Ui.Scroll(Ui.Column(Ui.Text("4 · 下载与素材制作",28),
            Ui.Text("当前接入H9单星、11K JPG＋500m/1km独立夜景。其他卫星或档位会在下载前拒绝，不会静默替换。",14,true),
            new Expander{Header="共享夜景参考 · 跨项目复用",Content=Ui.Column(Ui.Text("静态地面灯光底图，跨项目复用；这是地面夜景，不是夜间红外云图。已配置的参考会自动显示，无需每个项目重选。",13,true),nightStatus,nightPath,Ui.Button("检查并保存夜景参考",()=>NightRequested?.Invoke(nightPath.Text.Trim())),Ui.Button("检查当前参考状态",()=>NightStatusRequested?.Invoke()))},
            Ui.Card(Ui.Column(progress.Content,new Expander{Header="查看任务详情",Content=Ui.Column(planText,progressViewport,connection)})),
            new Expander{Header="计划与范围管理",Content=Ui.Column(readiness,plan,reuse,Ui.Text("先设置本项目日期并完成目录检查；选择已完成项目的 .earthproj 文件。重叠素材直接复用，只制作缺少的时次。源素材目录须保留。",13,true),Ui.Button("追加已检查的新范围（运行中也可加入）",()=>AppendRequested?.Invoke()),folder)},
            new Expander{Header="并行与校验设置",Content=Concurrency.Content},
            new Expander{Header="调整后续制作范围 · UTC",Content=Ui.Column(Ui.Text("先在第2步调整日期并完成第3步检查，再用上方按钮追加。取消仅针对未开始时次；已开始时次安全完成，已有JPG保留。",13,true),cancelStart.Content,cancelEnd.Content,cancelRangeError,Ui.Button("取消此范围内未开始的时次（保留JPG）",SubmitCancelRange))},gaps,start,pause,
            immediatePause,open,accepted,approve,sequence,
            Ui.Button("追加后更新我编辑过的Blender（另存副本）",()=>UpdateBlenderRequested?.Invoke()),deliveryText,browseDelivery,openDeliveryBlend,
            Ui.Text("无人值守：临时断网持续自动重连，资源不足自动等待；后台意外退出自动恢复，运行时阻止自动休眠。主动暂停始终有效。数据身份或质量校验失败会保留输入并明确停止。每帧完整检查图片与依赖，验证通过才清理自己的L1和中间文件；最终动画独立重开。",13,true),
            Ui.Text("已完成区间可另存为独立JPG动画包并进入运镜；单帧可交付图片并以固定天气设计运镜，序列可播放天气变化。未完成扫描不会被当作缺档。旧素材与工作区保留。",13,true)));
        UpdateButtons();
        LoadNightSetting();
    }
    private void SubmitCancelRange()
    {
        try
        {
            var first=cancelStart.Read();var last=cancelEnd.Read();
            if(first>last)throw new ArgumentException("取消终点不能早于起点。");
            cancelRangeError.Text="";
            CancelRangeRequested?.Invoke(first.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'"),last.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'"));
        }
        catch(ArgumentException error){cancelRangeError.Text=error.Message;}
    }
    public void LoadNightSetting()
    {
        var file=Path.Combine(AppPaths.UserData,"night_reference.json");
        if(!File.Exists(file)){nightStatus.Text="尚未配置共享夜景参考，请选择完整的全球VRT。";return;}
        try
        {
            using var document=JsonDocument.Parse(File.ReadAllText(file));
            nightPath.Text=document.RootElement.GetProperty("path").GetString()??"";
            nightStatus.Text=File.Exists(nightPath.Text)?"已载入本机保存的参考路径，正在等待依赖与像素读取检查。":"保存的参考路径已不存在，请重新选择。";
        }
        catch(Exception error){nightStatus.Text="读取夜景设置失败："+error.Message;}
    }
    public void SetNightReference(JsonElement value)
    {
        if(!value.TryGetProperty("night_valid",out var valid))return;
        if(valid.GetBoolean() && value.TryGetProperty("night_path",out var path))nightPath.Text=path.GetString()??"";
        nightStatus.Text=value.TryGetProperty("message",out var message)?message.GetString()??"":valid.GetBoolean()?"夜景参考可用":"夜景参考检查未通过";
    }
    public void SetDelivery(string path){delivery=path;deliveryText.Text="已交付："+path;UpdateButtons();}
    public void SetReadiness(bool ready,string message){canPlan=ready;readiness.Text=message;UpdateButtons();}
    public void SetQueueMatch(bool match){queueMatches=match;UpdateButtons();}
    public void LoadMissingDecision(bool value){gaps.IsChecked=value;}
    public void SetBusy(bool value,bool ownsProduction=false){busy=value;ownedProduction=ownsProduction;UpdateButtons();}
    public void Observe(Services.QueueSnapshot snapshot,bool pending)
    {
        externalActive=snapshot.Active;activityKnown=true;pausePending=pending;
        Accept(snapshot.State);
        var stopped=EarthStudio.Core.QueueControlState.Evaluate(busy,externalActive,true,pausePending,currentPhase).Stopped;
        connection.Text=externalActive?(pausePending?"已请求安全暂停，等待当前批次完成验证和清理。":"任务正在运行，进度已自动连接。"):
            stopped?"后台已停止，已完成结果保留，可点击继续。":"";
        if(stopped)status.Text=$"已完成 {completedCount} / {total} 个时次\n后台已停止，可从已保存进度继续。";
        UpdateButtons();
    }
    public void ConnectionUnavailable(){activityKnown=false;connection.Text="暂时无法确认后台状态，正在重试；避免重复启动。";UpdateButtons();}
    public void Paused(){status.Text="队列已暂停；已下载文件和完成结果保留，可点击继续。";}
    public void Clear(){progress.Clear();externalActive=false;activityKnown=true;pausePending=false;currentPhase="";connection.Text="";completedCount=0;delivery=null;deliveryText.Text="尚未交付素材。";hasPlan=false;hasReadable=false;queueMatches=true;sample=null;needsQuality=false;accepted.IsChecked=false;planText.Text="先完成第3步数据检查，再生成制作计划。";status.Text="尚未启动下载";UpdateButtons();}
    public void Bind(JsonElement value)
    {
        hasPlan=true;sample=null;needsQuality=false;
        var single=value.GetProperty("project").TryGetProperty("CaptureMode",out var mode)&&mode.GetString()=="single";
        sequence.Content=single?"交付单帧图片 → 预览 / 运镜 / Blender":"打开已完成序列 → 预览 / 运镜 / Blender";
        var count=value.GetProperty("steps").GetArrayLength();
        total=count;
        var downloaded=value.GetProperty("download_bytes").GetInt64()/1073741824.0;
        var estimated=value.GetProperty("estimated_final_bytes").GetInt64()/1073741824.0;
        var required=value.GetProperty("minimum_start_free_bytes").GetInt64()/1073741824.0;
        var keep=value.GetProperty("project").GetProperty("Production");
        planText.Text=$"{(single?"单帧图片":"延时时间序列")} · H9 · {count} 个精确扫描；缺档/不匹配 {value.GetProperty("missing_nodes").GetInt32()} 个节点。\n未计缓存的L1总量 {downloaded:F2} GB；正式成果估算 {estimated:F2} GB。每次启动至少需 {required:F2} GB 可用空间，执行中持续检查。\n保留L1：{keep.GetProperty("KeepL1").GetBoolean()}；保留中间文件：{keep.GetProperty("KeepIntermediates").GetBoolean()}。";
        if(value.TryGetProperty("reused_scans",out var reused))
        {
            var fresh=value.GetProperty("new_scans").GetInt32();
            var summary=$"已复用 {reused.GetInt32()} 个时次，只需制作 {fresh} 个新增时次。";
            planText.Text=summary+"\n"+planText.Text;
            readiness.Text=summary+" 源素材目录须保留；重叠时次不会再次下载或制作。";
        }
        accepted.IsChecked=false;UpdateButtons();
    }
    public void Accept(JsonElement value)
    {
        if(value.TryGetProperty("plan",out var p))Bind(p);
        if(!value.TryGetProperty("phase",out var field))return;
        var phase=field.GetString();needsQuality=phase=="awaiting-quality";
        currentPhase=phase??"";
        if(value.TryGetProperty("package",out var package))sample=package.GetString();
        hasReadable=phase=="complete" || (sample!=null && File.Exists(Path.Combine(sample,"blender_reopen.json")));
        status.Text=PipelineStatusText.Describe(value);
        if(value.TryGetProperty("completed",out var completed)&&completed.ValueKind==JsonValueKind.Array)completedCount=completed.GetArrayLength();
        if(value.TryGetProperty("completed_count",out var number))completedCount=number.GetInt32();
        status.Text=$"已完成 {completedCount} / {total} 个时次\n"+status.Text;
        progress.Update(value,completedCount,total);
        accepted.Visibility=needsQuality?Visibility.Visible:Visibility.Collapsed;
        UpdateButtons();
    }
    private void UpdateButtons()
    {
        reuse.IsEnabled=canPlan && !busy && !externalActive && !hasPlan;
        var control=EarthStudio.Core.QueueControlState.Evaluate(busy,externalActive,activityKnown,pausePending,currentPhase);
        var active=control.Busy;
        browseDelivery.IsEnabled=!active&&delivery!=null;
        openDeliveryBlend.IsEnabled=!active&&delivery!=null;
        plan.IsEnabled=!active&&canPlan;folder.IsEnabled=!active;start.IsEnabled=control.CanStart&&hasPlan&&!needsQuality&&queueMatches;
        start.Content=externalActive?(pausePending?"正在完成当前批次":"正在制作"):"开始 / 继续下载与制作";
        pause.Content=pausePending?"正在安全暂停…":"安全暂停（完成当前批）";
        sequence.IsEnabled=!active&&hasPlan&&hasReadable;
        approve.IsEnabled=!active&&queueMatches&&needsQuality&&accepted.IsChecked==true;approve.Visibility=needsQuality?Visibility.Visible:Visibility.Collapsed;
        open.IsEnabled=!active&&sample!=null;pause.IsEnabled=control.CanPause;gaps.IsEnabled=!active;accepted.IsEnabled=!active;
        immediatePause.IsEnabled=ownedProduction;
        ToolTipService.SetToolTip(immediatePause,ownedProduction?null:"当前任务请使用安全暂停，已完成结果和预取输入会保留。");
    }
    private void OpenSample()
    {
        if(sample==null)return;var file=Path.Combine(sample,"EarthStudio_JPEG_独立灯光.blend");
        if(!File.Exists(file)){status.Text="首样尚未生成。";return;}
        var launch=new ProcessStartInfo(AppPaths.BlenderExecutable){UseShellExecute=false};
        launch.ArgumentList.Add(file);launch.ArgumentList.Add("--disable-autoexec");
        try {Process.Start(launch);}
        catch(Exception error) {status.Text="无法打开Blender："+error.Message+"。样本仍保存在："+file;}
    }
}
