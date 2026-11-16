using System.Text.Json;
using EarthStudio.App.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.Web.WebView2.Core;

namespace EarthStudio.App.UI;

sealed class CesiumWorkspaceView : IDisposable
{
    public Grid Content { get; } = new() { Padding = new Thickness(8), RowSpacing = 4 };
    public Guid ProjectId { get; set; }
    public Func<Task<string?>>? MusicPicker { get; set; }
    public Func<Task<string?>>? BlenderPicker { get; set; }
    private bool pickingMusic;
    public event Action? FolderRequested;
    public event Action<string>? FolderChanged;
    private readonly WebView2 web = new();
    private readonly LocalStudioHost host = new();
    private readonly WorkspaceDocumentStore documents = new();
    private readonly BlenderExportService blender = new();
    private readonly TextBlock status = Ui.Text("打开已有素材，开始设计运镜。不会自动下载或重处理。", 12, true);
    private readonly ComboBox renderMode = new() { Width = 210 };
    private readonly Button export, openBlend, cancel, locate;
    private readonly TextBlock sourceInfo=Ui.Text("尚未载入素材。可打开已有素材包，或到第4步完成制作并交付。",14);
    private readonly ProgressBar exportProgress=new(){Height=5,Minimum=0,Maximum=100,Visibility=Visibility.Collapsed};
    private readonly TextBlock exportElapsed=Ui.Text("",11,true);
    private string? folder, lastBlend, restoreScript;
    private bool lastHigh22k, handlersAttached, loading;
    private bool layered;
    private Uri? origin;
    private TaskCompletionSource<string>? requestedExport;
    private CancellationTokenSource? importing;

    public CesiumWorkspaceView()
    {
        renderMode.Items.Add("11K PNG · 已验证素材"); renderMode.Items.Add("22K TIFF · 高细节素材"); renderMode.SelectedIndex = 0;
        renderMode.Items.Add("JPG分层 · 当前素材包");
        export = Ui.Button("生成Blender工程", () => Run(()=>ExportAsync()), true);
        openBlend = Ui.Button("打开已生成工程", () => { if (lastBlend != null) { try { blender.Open(lastBlend, lastHigh22k); } catch (Exception e) { status.Text = e.Message; } } });
        openBlend.IsEnabled = false;export.IsEnabled=false;renderMode.IsEnabled=false;
        cancel = Ui.Button("取消导出", () => importing?.Cancel()); cancel.IsEnabled = false;
        var tools = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        tools.Children.Add(Ui.Button("打开素材", () => FolderRequested?.Invoke()));
        var updateProject=Ui.Button("更新已有Blender运镜",()=>Run(async()=>{var source=BlenderPicker==null?null:await BlenderPicker();if(source!=null)await ExportAsync(source);}));
        ToolTipService.SetToolTip(updateProject,"请先在Blender保存大气、材质等修改，再选择该工程；将保存运镜修订副本，保留原文件。");
        var parameterLocation=Ui.Button("运镜参数位置",()=>{var path=lastBlend!=null?Path.GetDirectoryName(lastBlend)!:Path.Combine(AppPaths.UserData,"ShotPlans");Directory.CreateDirectory(path);System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(path){UseShellExecute=true});});
        var saveParameters=Ui.Button("保存完整运镜",()=>Run(async()=>{await web.ExecuteScriptAsync("document.getElementById('projectSave').click()");}));
        tools.Children.Add(new Expander{Header="更新 / 参数",Content=Ui.Column(Ui.Text("先在Blender保存外观，再更新运镜。",11,true),updateProject,saveParameters,parameterLocation)});
        locate=Ui.Button("打开素材位置",()=>
        {
            if(folder==null)return;
            try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(folder){UseShellExecute=true}); }
            catch(Exception error) { status.Text="无法打开素材目录："+error.Message; }
        });
        locate.IsEnabled=false;tools.Children.Add(locate);
        var examples=Ui.Column(Ui.Text("示例与验收素材不属于当前项目制作结果。",13,true),
            Ui.Button("H9历史PNG验收素材",()=>Run(()=>SetFolderAsync(Path.Combine(AppPaths.FindEngineRoot()??"","data","cesium_h9_motion_20261020")))),
            Ui.Button("JPG两时次动态样本",()=>Run(()=>SetFolderAsync(Path.Combine(AppPaths.FindEngineRoot()??"","data","exports","H9_JPG_M5_20261020_1300_1310")))));
        tools.Children.Add(new Expander{Header="示例素材",Content=examples});

        tools.Children.Add(renderMode); tools.Children.Add(export); tools.Children.Add(openBlend); tools.Children.Add(cancel);
        Content.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        Content.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        Content.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        sourceInfo.TextTrimming=TextTrimming.CharacterEllipsis;sourceInfo.TextWrapping=TextWrapping.NoWrap;sourceInfo.MaxLines=1;
        status.TextTrimming=TextTrimming.CharacterEllipsis;status.TextWrapping=TextWrapping.NoWrap;status.MaxLines=1;
        var commandScroll=new ScrollViewer{Content=tools,HorizontalScrollBarVisibility=ScrollBarVisibility.Auto,VerticalScrollBarVisibility=ScrollBarVisibility.Disabled};
        Content.Children.Add(Ui.Column(commandScroll,sourceInfo)); var progressArea=Ui.Column(status,exportProgress,exportElapsed);Grid.SetRow(progressArea, 1);Content.Children.Add(progressArea); Grid.SetRow(web, 2); Content.Children.Add(web);
    }

    private async void Run(Func<Task> action) { try { await action(); } catch (OperationCanceledException) { status.Text = "导出已取消；正式素材和旧工程保留。"; } catch (TimeoutException) { status.Text = "未收到有效运镜；请先添加关键帧后重试。"; } catch (Exception e) { status.Text = e.Message; } }

    public async Task SetFolderAsync(string path)
    {
        if (loading || importing != null) throw new InvalidOperationException("请先等待素材载入或完成Blender导出。");
        loading = true;
        try
        {
            var full = Path.GetFullPath(path);
            using var manifest = JsonDocument.Parse(await File.ReadAllTextAsync(Path.Combine(full, "manifest.json")));
            var frames = manifest.RootElement.GetProperty("frames");
            if(frames.GetArrayLength()==0)throw new ArgumentException("素材包中没有可预览时次，请先完成第4步。");
            layered=manifest.RootElement.TryGetProperty("layeredSequence",out var marker)&&marker.GetBoolean();
            var first=DateTimeOffset.Parse(frames[0].GetProperty("utc").GetString()!).UtcDateTime;
            var last=DateTimeOffset.Parse(frames[frames.GetArrayLength()-1].GetProperty("utc").GetString()!).UtcDateTime;
            sourceInfo.Text=$"{ReadableNames.MaterialTitle(full)} · {(layered?"JPG分层素材":"卫星影像素材")} · {frames.GetArrayLength()}个观测节点 · {first:yyyy-MM-dd HH:mm} → {last:yyyy-MM-dd HH:mm} UTC";
            ToolTipService.SetToolTip(sourceInfo,full);ToolTipService.SetToolTip(locate,full);
            renderMode.SelectedIndex=layered?2:0;renderMode.IsEnabled=!layered;
            var missing = frames.EnumerateArray().Count(f => f.TryGetProperty("missing", out var m) && m.GetBoolean());
            status.Text = $"载入素材：{frames.GetArrayLength()}个节点，{missing}个缺档；正在启动本机渲染服务…";
            var uri = await host.StartAsync(full);
            await web.EnsureCoreWebView2Async();

            if (!handlersAttached)
            {
                handlersAttached = true;
                web.CoreWebView2.NavigationStarting += (_, e) => { if (origin == null || !e.Uri.StartsWith(origin.AbsoluteUri, StringComparison.Ordinal)) e.Cancel = true; };
                web.CoreWebView2.NewWindowRequested += (_, e) => e.Handled = true;
                web.CoreWebView2.WebMessageReceived += MessageReceived;

            }
            if (restoreScript != null) web.CoreWebView2.RemoveScriptToExecuteOnDocumentCreated(restoreScript);
            var draft = await documents.ReadDraftAsync(full, ProjectId);
            var value = draft == null ? "localStorage.removeItem('earthstudio.timeline.editor.v1');" : "localStorage.setItem('earthstudio.timeline.editor.v1'," + JsonSerializer.Serialize(draft) + ");";
            restoreScript = await web.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(value);
            origin = uri; folder = full; locate.IsEnabled=true;web.Visibility = Visibility.Visible;
            web.Source = new Uri(uri, "index.html");export.IsEnabled=true; FolderChanged?.Invoke(full);
            status.Text = $"{frames.GetArrayLength() - missing}幅真实观测 / {missing}个缺档 · {(layered?"JPG分层动画包；网页为默认夜景显示预览，独立夜景调色在Blender":"H9验收素材")} · 运镜草稿自动保存";
        }
        finally { loading = false; }
    }

    private async void MessageReceived(CoreWebView2 sender, CoreWebView2WebMessageReceivedEventArgs args)
    {
        if (origin == null || !args.Source.StartsWith(origin.AbsoluteUri, StringComparison.Ordinal)) return;
        try
        {
            using var message = JsonDocument.Parse(args.WebMessageAsJson);
            var value = message.RootElement; var type = value.GetProperty("type").GetString();
            if(type=="music-import")
            {
                if(pickingMusic)return;pickingMusic=true;
                var sourceOrigin=origin;
                try
                {
                    var path=MusicPicker==null?null:await MusicPicker();
                    if(sourceOrigin!=origin)return;
                    if(path==null)sender.PostWebMessageAsJson(JsonSerializer.Serialize(new {type="music-imported",cancelled=true}));
                    else
                    {
                        var asset=await MusicAssetStore.ImportAsync(path);
                        if(sourceOrigin==origin)sender.PostWebMessageAsJson(JsonSerializer.Serialize(new {type="music-imported",asset}));
                    }
                }
                catch(Exception error){if(sourceOrigin==origin)sender.PostWebMessageAsJson(JsonSerializer.Serialize(new {type="music-imported",error=error.Message}));}
                finally{pickingMusic=false;}
            }
            else if (type == "ready") sender.PostWebMessageAsJson(JsonSerializer.Serialize(new { manifestUrl = new Uri(origin, "data/manifest.json").AbsoluteUri }));
            else if (type == "editor-autosave" && folder != null) await documents.SaveDraftAsync(folder, ProjectId, value.GetProperty("data"));
            else if (type is "camera-export" or "plan-export" or "render-plan-export")
            {
                var path = await documents.SaveAsync(type, value.GetProperty("data"));
                status.Text = "已保存：" + path;
                if (type == "camera-export") requestedExport?.TrySetResult(path);
            }
        }
        catch (Exception e) { requestedExport?.TrySetException(e); status.Text = "保存失败：" + e.Message; }
    }

    private async Task ExportAsync(string? existingBlend=null)
    {
        if (loading || origin == null || folder == null) throw new InvalidOperationException("先完成素材载入并添加关键帧。");
        if (importing != null) return;
        var expected = Path.Combine(AppPaths.FindEngineRoot()!, "data", "cesium_h9_motion_20261020");
        if (!layered && !Path.GetFullPath(folder).Equals(Path.GetFullPath(expected), StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("当前Blender模板仅验证H9验收素材；其他素材导出适配尚待接入。");
        importing = new(); export.IsEnabled = false; cancel.IsEnabled = true; renderMode.IsEnabled = false;
        exportProgress.Visibility=Visibility.Visible;exportProgress.IsIndeterminate=true;
        var timer=new DispatcherTimer{Interval=TimeSpan.FromSeconds(1)};var elapsed=System.Diagnostics.Stopwatch.StartNew();
        timer.Tick+=(_,_)=>exportElapsed.Text=$"已用时 {elapsed.Elapsed:hh\\:mm\\:ss} · 正在生成时可取消；预计时间按当前阶段进度更新";timer.Start();
        var high = renderMode.SelectedIndex == 1;var completed=false;
        requestedExport = new(TaskCreationOptions.RunContinuationsAsynchronously);
        try
        {
            var result = await web.ExecuteScriptAsync("(()=>{document.getElementById('exportAll').click();const f=document.getElementById('feedback');return {message:f.textContent,error:f.classList.contains('error')};})()");
            using(var feedback=JsonDocument.Parse(result))
            {
                var message=feedback.RootElement.GetProperty("message").GetString()??"等待运镜导出…";
                if(feedback.RootElement.GetProperty("error").GetBoolean())throw new InvalidOperationException(message);
                if(!requestedExport.Task.IsCompleted)status.Text=message;
            }
            var json = await requestedExport.Task.WaitAsync(TimeSpan.FromSeconds(120), importing.Token);
            status.Text = "正在校验素材并生成独立Blender工程；不会覆盖旧工程…";
            lastBlend = await blender.ImportAsync(json, high, importing.Token,layered?folder:null,(text,value)=>Content.DispatcherQueue.TryEnqueue(()=>{status.Text=text;exportProgress.IsIndeterminate=!value.HasValue;if(value.HasValue)exportProgress.Value=value.Value;}),existingBlend); lastHigh22k = high;
            completed=true;openBlend.IsEnabled = true; status.Text = "工程已生成，点击“打开已生成工程”：" + lastBlend;
        }
        finally { timer.Stop();exportElapsed.Text=completed?$"本次导出用时 {elapsed.Elapsed:hh\\:mm\\:ss}；完整运镜在同目录.timeline.json，相机快照.camera.json，逐帧UTC在.frames.csv":$"本次用时 {elapsed.Elapsed:hh\\:mm\\:ss}；未完成新工程，原工程保留";exportProgress.Visibility=Visibility.Collapsed;requestedExport = null; importing.Dispose(); importing = null; export.IsEnabled = true; cancel.IsEnabled = false; renderMode.IsEnabled = !layered; }
    }

    public void Clear() { if (loading || importing != null) throw new InvalidOperationException("先等待素材载入或完成导出。"); host.Dispose(); folder = null;locate.IsEnabled=false;ToolTipService.SetToolTip(locate,null); origin = null; web.Visibility = Visibility.Collapsed; lastBlend = null;export.IsEnabled=false;renderMode.IsEnabled=false; openBlend.IsEnabled = false; status.Text = "新项目：选择素材后开始运镜。";sourceInfo.Text="尚未载入素材。打开已有素材包，或到第4步完成制作。"; }

    public void Dispose() { importing?.Cancel(); host.Dispose(); web.Close(); }
}

