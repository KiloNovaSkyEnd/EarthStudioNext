using EarthStudio.Core;
using EarthStudio.App.Services;
using EarthStudio.App.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace EarthStudio.App;

sealed partial class MainWindow : Window
{
    private readonly ProjectView project = new();
    private readonly TasksView tasks = new();
    private readonly AccountsView accounts = new();
    private readonly ValidationView validation = new();
    private readonly UpgradeView upgrade = new();
    private readonly ProductionView production = new();
    private readonly ProductionJobsClient producer = new();
    private readonly ProductionDeliveryClient delivery = new();
    private readonly CesiumWorkspaceView cesium = new();
    private readonly ScrollViewer projectScroll;
    private readonly ProjectStore store = new();
    private readonly EngineClient engine = new();
    private readonly ScientificTasksClient scientific = new();
    private readonly NavigationView navigation = new() { IsSettingsVisible = false, OpenPaneLength = 260, PaneDisplayMode = NavigationViewPaneDisplayMode.Left };
    private readonly TextBlock status = Ui.Text("就绪 · 独立桌面开发版 · 素材与运镜工作区", 12, true);
    private readonly Button cancel;
    private readonly PickerService pickers;
    private CancellationTokenSource? running;
    private readonly BackgroundTaskLanes background=new();
    private string? projectFile;

    public MainWindow()
    {
        Title = "Earth Studio Next · M18 多镜头与Blender同步";
        status.TextWrapping=TextWrapping.NoWrap;status.TextTrimming=TextTrimming.CharacterEllipsis;status.MaxLines=1;
        project.Content.MinHeight = 680;
        projectScroll = new ScrollViewer { Content = project.Content, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
        SystemBackdrop = new MicaBackdrop();
        AppWindow.Resize(new Windows.Graphics.SizeInt32(1600, 1000));
        (AppWindow.Presenter as Microsoft.UI.Windowing.OverlappedPresenter)?.Maximize();
        pickers = new(WinRT.Interop.WindowNative.GetWindowHandle(this));
        cesium.MusicPicker = pickers.OpenMusicAsync;cesium.BlenderPicker=pickers.OpenBlenderAsync;
        var root = new Grid { RequestedTheme = ElementTheme.Dark, RowSpacing = 1 };
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        var toolbar = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10, Padding = new Thickness(20, 12, 20, 12) };
        toolbar.Children.Add(Ui.Text("EARTH STUDIO NEXT", 20));
        toolbar.Children.Add(Ui.Button("新建项目", () => Guard(NewProjectAsync)));
        toolbar.Children.Add(Ui.Button("打开项目", () => Guard(OpenAsync)));
        toolbar.Children.Add(Ui.Button("保存项目", () => Guard(SaveAsync), true));
        root.Children.Add(toolbar);
        ConfigureNavigation();
        navigation.PaneFooter = Ui.Text("账户 → 单帧/序列 → 数据检查\n素材制作 → 运镜 → Blender\n现有数据与工程保留", 12, true);
        navigation.SelectionChanged += (_, args) =>
        {
            project.Stop();RefreshWorkflow();
            var tag = (args.SelectedItem as NavigationViewItem)?.Tag as string;
            navigation.Content = tag switch { "pipeline"=>pipeline.Content, "production" => production.Content, "cesium" => cesium.Content, "tasks" => tasks.Content, "accounts" => accounts.Content, "validation" => validation.Content, "upgrade" => upgrade.Content, _ => projectScroll };
            if(tag=="pipeline")
            {
                pipeline.LoadNightSetting();
                if(running==null)Guard(()=>RunAsync(new {action="night-status"}));
            }
        };
        Grid.SetRow(navigation, 1); root.Children.Add(navigation);
        var footer = new Grid { Padding = new Thickness(20, 8, 20, 10) };
        footer.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        footer.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        footer.Children.Add(status);
        cancel = Ui.Button("取消后台任务", CancelSelectedOperation); cancel.Width=180; cancel.IsEnabled = false;
        Grid.SetColumn(cancel, 1); footer.Children.Add(cancel);
        Grid.SetRow(footer, 2); root.Children.Add(footer);
        Content = root;
        var initial = DefaultProject(); project.SetProject(initial); cesium.ProjectId = initial.Id;
        accounts.ContinueRequested += () => SelectPage("project");
        tasks.ResumeRequested += () => Guard(ScanAsync);
        tasks.RefreshRequested += () => Guard(() => ScanCatalogAsync(true));
        tasks.ImportRequested+=()=>Guard(async()=>{if(running!=null || background.IsActive(BackgroundLane.Catalog))throw new InvalidOperationException("请先完成或取消正在执行的检查，再导入外部记录。");var source=await pickers.FolderAsync();if(source!=null)await ImportCatalogAsync(source);});
        tasks.ImportFileRequested+=()=>Guard(async()=>{if(running!=null || background.IsActive(BackgroundLane.Catalog))throw new InvalidOperationException("请先完成或取消正在执行的检查，再导入外部记录。");var source=await pickers.OpenInventoryAsync();if(source!=null)await ImportCatalogAsync(source);});
        tasks.ContinueRequested += () => SelectPage("pipeline");
        ConfigurePipeline();
        project.ScanRequested += () => Guard(ScanAsync);
        project.TimingChanged += UpdateLiveCatalog;
        production.StartRequested += utc => Guard(async () =>
        {
            if (running != null) throw new InvalidOperationException("已有任务正在运行。");
            var settings=project.ReadProject();
            running=new CancellationTokenSource();cancel.IsEnabled=true;production.SetBusy(true);
            try {
                var output=await producer.RunAsync(settings,utc,message => DispatcherQueue.TryEnqueue(() => production.Report(message)),running.Token);
                production.SetPackage(output);
                production.Report("素材已提交，等待Blender分层验收："+output);
            }
            finally { running.Dispose();running=null;RefreshCancelButton();production.SetBusy(false); }
        });
        production.DeliveryRequested += (package,action) => Guard(async () =>
        {
            if (running != null) throw new InvalidOperationException("已有任务正在运行。");
            running=new CancellationTokenSource();cancel.IsEnabled=true;production.SetBusy(true);
            try { await delivery.RunAsync(package,action,message => DispatcherQueue.TryEnqueue(() => production.Report(message)),running.Token); }
            finally { running.Dispose();running=null;RefreshCancelButton();production.SetBusy(false); }
        });
        cesium.FolderRequested += () => Guard(async () => { var path = await pickers.FolderAsync(); if (path != null) await cesium.SetFolderAsync(path); });
        cesium.FolderChanged += path => Guard(async()=>{project.SetMaterialsDirectory(path);await SaveWorkingProjectAsync();});
        project.FolderRequested += () => Guard(async () => { var path = await pickers.FolderAsync(); if (path != null) {AppPaths.RegisterDataDirectory(path);project.SetDirectory(path);status.Text="项目数据目录已登记；原目录中的检查记录可在第3步导入复用。";} });
        accounts.ConnectRequested += (key, secret) => Guard(() => ConnectAsync(key, secret));
        validation.FolderRequested += () => Guard(async () => { var path = await pickers.FolderAsync(); if (path != null) await validation.SetRootAsync(path); });
        validation.StartRequested += (folder,blender) => Guard(async () =>
        {
            if (running!=null) throw new InvalidOperationException("已有任务正在运行。");
            running=new CancellationTokenSource(); cancel.IsEnabled=true; validation.SetBusy(true);
            try { status.Text="本机下载与处理运行中，进度见测试工作区。"; await scientific.RunAsync(folder,blender,running.Token); status.Text="小样导出结束，等待画面验收。"; }
            finally { running.Dispose(); running=null; RefreshCancelButton(); validation.SetBusy(false); }
        });
        SelectPage("accounts");
        root.Loaded += (_, _) =>
        {
            Guard(async()=>{try{await AccountStatusAsync();}catch(Exception error){status.Text=error.Message;}await RestoreRecentProjectAsync();});
        };
        Closed += (_, _) => { project.Stop(); running?.Cancel(); background.Dispose(); cesium.Dispose(); };
    }
    private static EarthProject DefaultProject(bool fresh = true) => new() { Id = fresh ? Guid.NewGuid() : Guid.Parse("10a783d2-3491-4548-9e21-e77240e22200"), DataDirectory = Path.Combine(AppPaths.UserData, "Data"), StartUtc = new(2026,10,20,13,0,0,TimeSpan.Zero), EndUtc = new(2026,10,21,1,0,0,TimeSpan.Zero), IntervalMinutes = 10, SatelliteSelection = new() { Mode="manual", Preset="h9", Satellites=new[]{"himawari9"} } };
    private void SelectPage(string tag) => navigation.SelectedItem=NavigationItems(navigation.MenuItems).Single(item => (string)item.Tag==tag);
    private async void Guard(Func<Task> action)
    {
        try { await action(); }
        catch (OperationCanceledException) { status.Text = "任务已取消；已检查的目录记录保留。"; }
        catch (Exception e) { status.Text = e.Message; }
    }
    private async Task NewProjectAsync()
    {
        if (running != null || background.IsActive(BackgroundLane.Production) || background.IsActive(BackgroundLane.Catalog) || background.IsActive(BackgroundLane.QueueEdit)) throw new InvalidOperationException("请先完成当前操作；运行中扩大时间范围可直接在当前项目修改日期。");
        var dialog = new ContentDialog { XamlRoot = ((FrameworkElement)Content).XamlRoot, Title = "新建项目？",
            Content = "当前编辑内容不会自动保存。", PrimaryButtonText = "新建", CloseButtonText = "返回" };
        if (await dialog.ShowAsync() == ContentDialogResult.Primary) { cesium.Clear();ClearPipeline(); projectFile = null;RecentProject.Save(null); var value = DefaultProject(true); project.SetProject(value); cesium.ProjectId = value.Id; status.Text = "已新建项目"; }
    }
    private async Task OpenAsync()
    {
        if (running != null || background.IsActive(BackgroundLane.Production) || background.IsActive(BackgroundLane.Catalog) || background.IsActive(BackgroundLane.QueueEdit)) throw new InvalidOperationException("请先完成当前操作；运行中扩大时间范围可直接在当前项目修改日期。");
        var path = await pickers.OpenProjectAsync();
        if (path == null) return;
        await OpenProjectPathAsync(path);
    }
    private async Task OpenProjectPathAsync(string path)
    {
        var loaded = await store.LoadAsync(path); AppPaths.RegisterDataDirectory(loaded.DataDirectory); cesium.Clear();ClearPipeline(); cesium.ProjectId = loaded.Id; project.SetProject(loaded); projectFile = path; status.Text = $"已打开：{Path.GetFileName(path)}";
        if(loaded.MaterialsDirectory!=null)pipeline.SetDelivery(loaded.MaterialsDirectory);
        await RestoreCatalogAsync(loaded);
        var hasQueue=loaded.PipelineDirectory!=null && Directory.Exists(loaded.PipelineDirectory);
        if(hasQueue){queues.Attach(loaded.PipelineDirectory!);RefreshPipeline();SelectPage("pipeline");}
        // Production queues and prepared editing materials coexist. Restoring a
        // queue must not leave stage5 empty after the user reopens the project.
        if(loaded.MaterialsDirectory!=null)
        {
            if(Directory.Exists(loaded.MaterialsDirectory))
            {
                await cesium.SetFolderAsync(loaded.MaterialsDirectory);
                if(!hasQueue || queues.Read("state.json").GetProperty("phase").GetString()=="complete")SelectPage("cesium");
            }
            else status.Text="项目已打开；素材目录当前不可用，请在第5步重新定位素材。";
        }
        RecentProject.Save(path);
    }
    private async Task SaveAsync()
    {
        var value = project.ReadProject();
        var path = projectFile ?? await pickers.SaveProjectAsync(value.Name);
        if (path == null) return;
        AppPaths.RequireWritable(path);
        await store.SaveAsync(path, value); projectFile = path;RecentProject.Save(path); status.Text = "项目已保存";
    }
    private Task ScanAsync() => ScanCatalogAsync(false);
    private async Task ConnectAsync(string key, string secret)
    {
        if (string.IsNullOrWhiteSpace(key) || string.IsNullOrWhiteSpace(secret)) throw new ArgumentException("请填写 Consumer Key 与 Secret。");
        try { await RunAsync(new { action = "connect-account", options = new { key, secret } }); }
        finally { accounts.ClearSecret(); }
    }
    private Task AccountStatusAsync() => RunAsync(new { action = "account-status" });
    private async Task RunAsync(object request)
    {
        if (running != null) throw new InvalidOperationException("已有任务运行，请等待或取消。");
        running = new CancellationTokenSource(); cancel.IsEnabled = true; accounts.SetBusy(true);
        status.Text = "后台任务运行中…";
        try
        {
            await engine.RunAsync(request, message =>
            {
                tasks.Accept(message);
                pipeline.SetNightReference(message);
                if (message.TryGetProperty("message", out var text)) status.Text = text.GetString() ?? "";
                if (message.TryGetProperty("configured", out var configured)) accounts.SetStatus(configured.GetBoolean() ? status.Text : "尚未连接本机账户");
            }, running.Token);
        }
        finally { running.Dispose(); running = null; RefreshCancelButton(); accounts.SetBusy(false); }
    }
}
