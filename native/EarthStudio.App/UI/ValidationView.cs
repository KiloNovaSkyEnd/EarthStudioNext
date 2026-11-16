using System.Diagnostics;
using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EarthStudio.App.UI;

sealed class ValidationView
{
    public Grid Content { get; } = new() { Padding = new Thickness(24), RowSpacing = 12 };
    public event Action? FolderRequested;
    public event Action<string,string>? StartRequested;
    private readonly TextBox blenderInput = new() { Header = "本机 Blender.exe 路径" };
    private readonly Button startProcessing = new() { Content = "继续完整时段处理并导出 Blender" };
    private readonly CheckBox atmosphere = new() { Content="柔和大气", IsChecked=true };
    private readonly Dictionary<string,double[]> suns = new();
    private readonly GlobeView globe = new();
    private readonly TextBlock status = Ui.Text("选择现有测试目录，读取实际任务状态和已生成的天气。", 14);
    private readonly TextBlock location = Ui.Text("尚未选择测试目录", 12, true);
    private readonly TextBox directoryInput = new() { Header = "测试根目录", PlaceholderText = "选择或粘贴含 inventory.json 的目录", MinWidth = 520 };
    private readonly Slider timeline = new() { Minimum = 0, Maximum = 1, StepFrequency = 1, IsEnabled = false };
    private readonly DispatcherTimer refresh = new() { Interval = TimeSpan.FromSeconds(3) };
    private readonly DispatcherTimer play = new() { Interval = TimeSpan.FromMilliseconds(1100) };
    private readonly Button playButton = new();
    private string? root;
    private bool reading;
    private string? signature;
    private string? weatherFolder;
    private readonly List<(string File, string Utc)> frames = new();

    public ValidationView()
    {
        Content.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        Content.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        Content.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        var controls = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12 };
        controls.Children.Add(Ui.Button("打开测试目录", () => FolderRequested?.Invoke(), true));
        controls.Children.Add(Ui.Button("载入填写的目录", async () => { try { await SetRootAsync(directoryInput.Text); } catch(Exception e) { status.Text=e.Message; } }));
        controls.Children.Add(Ui.Button("打开日志与报告", () => OpenFolder("reports")));
        controls.Children.Add(Ui.Button("打开 Blender 导出目录", () => OpenFolder("exports")));
        controls.Children.Add(atmosphere);
        atmosphere.Checked += (_,_)=>ShowFrame(); atmosphere.Unchecked += (_,_)=>ShowFrame();
        startProcessing.Click += (_,_) => { if(root!=null) StartRequested?.Invoke(root,blenderInput.Text.Trim()); };
        var processing=new Expander { Header="下载与处理设置", HorizontalAlignment=HorizontalAlignment.Stretch,
            Content=Ui.Column(blenderInput,startProcessing,Ui.Text("使用已下载的测试清单；恢复原生全局处理、独立导出场景及核验视频；旧归档仅允许只读预览。新镜头可在Blender内重新取材。",12,true)) };
        playButton.Content = "播放已完成天气";
        playButton.Padding = new Thickness(16,9,16,9);
        playButton.Click += (_, _) =>
        {
            if (play.IsEnabled) { play.Stop(); playButton.Content = "播放已完成天气"; }
            else if (frames.Count > 0) { play.Start(); playButton.Content = "暂停天气"; }
        };
        Content.Children.Add(Ui.Column(Ui.Text("卫星地球 · 测试工作区", 28), directoryInput, controls, processing, location, status));
        var card = Ui.Card(globe.Content, new Thickness(0)); card.MinHeight = 300;
        Grid.SetRow(card, 1); Content.Children.Add(card);
        var bottom = Ui.Column(timeline, playButton,
            Ui.Text("仅播放实际完成的观测；灰色为缺测，预览图不代表最终细节。最终交付要求完整时段和全球原生细节，不以当前机位局部代替。", 12, true));
        Grid.SetRow(bottom, 2); Content.Children.Add(bottom);
        timeline.ValueChanged += (_, _) => ShowFrame();
        play.Tick += (_, _) => timeline.Value = timeline.Value >= frames.Count-1 ? 0 : timeline.Value+1;
        refresh.Tick += async (_, _) => await RefreshAsync();
        Content.Loaded += async (_, _) =>
        {
            refresh.Start();
            var preference = Path.Combine(AppPaths.UserData,"validation-directory.txt");
            if (root == null && File.Exists(preference))
            { try { await SetRootAsync((await File.ReadAllTextAsync(preference)).Trim()); } catch(Exception e) { status.Text=e.Message; } }
            else await RefreshAsync();
        };
        Content.Unloaded += (_, _) => { refresh.Stop(); play.Stop(); playButton.Content = "播放已完成天气"; };
    }
    public async Task SetRootAsync(string folder)
    {
        if (!File.Exists(Path.Combine(folder, "inventory.json"))) throw new ArgumentException("请选择含 inventory.json 的测试根目录。");
        root = Path.GetFullPath(folder); location.Text = root; directoryInput.Text=root; signature = null;
        using var config=await ReadAsync(Path.Combine(root,"project.json"));
        if (config?.RootElement.TryGetProperty("blender_executable",out var executable)==true) blenderInput.Text=executable.GetString()??"";
        Directory.CreateDirectory(AppPaths.UserData);
        await File.WriteAllTextAsync(Path.Combine(AppPaths.UserData,"validation-directory.txt"),root);
        play.Stop(); frames.Clear(); timeline.IsEnabled = false;
        await RefreshAsync();
    }
    public void SetBusy(bool busy) => startProcessing.IsEnabled=!busy;
    private void OpenFolder(string name)
    {
        if (root != null && Directory.Exists(Path.Combine(root,name)))
            Process.Start(new ProcessStartInfo(Path.Combine(root,name)) { UseShellExecute = true });
    }
    private static async Task<JsonDocument?> ReadAsync(string path)
    {
        if (!File.Exists(path)) return null;
        return JsonDocument.Parse(await File.ReadAllTextAsync(path));
    }
    private async Task RefreshAsync()
    {
        if (reading || root == null) return;
        reading = true;
        try
        {
            using var full = await ReadAsync(Path.Combine(root,"reports","full_pipeline_status.json"));
            using var sequence = await ReadAsync(Path.Combine(root,"reports","sequence_status.json"));
            using var job = await ReadAsync(Path.Combine(root,"reports","stock_job_status.json"));
            using var capability = await ReadAsync(Path.Combine(root,"reports","stock_capabilities.json"));
            using var night = await ReadAsync(Path.Combine(root,"reports","night_download_progress.json"));
            using var compute = await ReadAsync(Path.Combine(root,"reports","compute_progress.json"));
            var stage = job?.RootElement.GetProperty("stage").GetString() ?? "尚无处理记录";
            stage = stage switch { "checking_archive" => "核验原始数据", "building_shared_night_proxy" => "准备共享夜间预览", "stock_proxy" => "生成卫星天气预览", "native_tile" => "读取原始波段、处理原生细节瓦片", "night_registration" => "核验夜光地理导航", "pilot_assets_ready" => "小样素材完成，等待画面验收", "failed" => "处理失败", _ => stage };
            var detail = job?.RootElement.TryGetProperty("error",out var error) == true ? " · "+error.GetString() : "";
            if(full!=null)
            {
                stage=full.RootElement.GetProperty("stage").GetString()??stage;
                detail=full.RootElement.TryGetProperty("error",out var failure)?" · "+failure.GetString():"";
                if(stage=="complete_observation_sequence" && sequence?.RootElement.TryGetProperty("node",out var node)==true)
                    detail+=$" · {node.GetInt32()}/73 · {sequence.RootElement.GetProperty("stage").GetString()}";
                if(stage=="preparing_camera_original_detail" && full.RootElement.TryGetProperty("request",out var request))
                {
                    using var nativeStatus=await ReadAsync(Path.ChangeExtension(request.GetString()!,".status.json"));
                    if(nativeStatus!=null) detail+=" · "+nativeStatus.RootElement.GetProperty("stage").GetString();
                }
            }
            var blockers = capability == null ? "尚无核验" : string.Join("、", capability.RootElement.GetProperty("global_blockers").EnumerateArray().Select(e=>e.GetString()));
            if (blockers == "") blockers="无配方阻塞；接缝、画质、原生细节仍待验收";
            var speed = night != null && night.RootElement.TryGetProperty("bytes_per_second",out var bytes) ? bytes.GetDouble()/1_000_000 : 0;
            var nightText=night?.RootElement.GetProperty("stage").GetString()=="completed"?"全球500m夜背景已齐备":$"夜光下载 {speed:F1} MB/s";
            stage=stage switch {
                "complete_observation_sequence"=>"准备完整天气时间序列", "building_editable_scene"=>"建立可编辑地球",
                "measuring_camera_footprint"=>"计算镜头所需细节", "preparing_camera_original_detail"=>"准备镜头的原始卫星细节",
                "assembling_camera_scene"=>"生成可运镜场景", "rendering_verification_video"=>"渲染检验视频",
                "decoding_verification_video"=>"核验视频完整性", "ready_for_user_review"=>"场景和视频已生成，等待观看确认",
                "failed"=>"任务失败，请查看报告", _=>stage };
            var sameScene=compute!=null && job?.RootElement.TryGetProperty("scene_id",out var sceneId)==true && sceneId.GetString()==compute.RootElement.GetProperty("scene_id").GetString();
            var tasks = !sameScene ? "" : $" · 计算任务 {compute!.RootElement.GetProperty("finished_tasks").GetInt32()} / {compute.RootElement.GetProperty("graph_tasks").GetInt32()}（工作量不同，不是预计剩余时间）";
            status.Text = $"处理阶段：{stage}{detail}{tasks}\n全球验收：{blockers} · {nightText}\n欧洲/非洲、印度洋采用已批准的真实自然色，与原生 GeoColor 有差异。";
            var completeProxy=Path.Combine(root,"processed","stock_geocolor","global_sequence_4k");
            var proxy = Directory.Exists(completeProxy)?completeProxy:Path.Combine(root,"processed","stock_geocolor","global_proxy");
            weatherFolder=proxy;
            if (!Directory.Exists(proxy)) return;
            var files = Directory.GetFiles(proxy,"weather_*.json").Order().ToArray();
            var sequenceAssets=Path.Combine(root,"processed","stock_geocolor","blender_sequence_assets","scene_assets.json");
            var assets=File.Exists(sequenceAssets)?sequenceAssets:Path.Combine(root,"processed","stock_geocolor","blender_assets","scene_assets.json");
            var current = string.Join(";",files.Select(f=>f+File.GetLastWriteTimeUtc(f).Ticks))+(File.Exists(assets)?File.GetLastWriteTimeUtc(assets).Ticks:0);
            if (current == signature) return;
            suns.Clear();
            using var sceneAssets=await ReadAsync(assets);
            if (sceneAssets!=null)
                foreach(var frame in sceneAssets.RootElement.GetProperty("frames").EnumerateArray())
                {
                    var sun=frame.GetProperty("sun").EnumerateArray().Select(c=>c.GetDouble()).ToArray();
                    if(sun.Length==3 && sun.All(double.IsFinite)) suns[frame.GetProperty("nominal_utc").GetString()!]=sun;
                }
            var updated = new List<(string,string)>();
            foreach (var file in files)
            {
                using var metadata = await ReadAsync(file);
                if (metadata == null) continue;
                var png = Path.ChangeExtension(file,".png");
                if(metadata.RootElement.TryGetProperty("sun",out var solar))
                    suns[metadata.RootElement.GetProperty("nominal_utc").GetString()!]=solar.EnumerateArray().Select(v=>v.GetDouble()).ToArray();
                if (File.Exists(png)) updated.Add((Path.GetFileName(png),metadata.RootElement.GetProperty("nominal_utc").GetString()!));
            }
            frames.Clear(); frames.AddRange(updated); signature = current;
            timeline.Maximum = Math.Max(1, frames.Count-1); timeline.IsEnabled = frames.Count>0;
            ShowFrame();
        }
        catch (IOException) { status.Text = "硬盘暂不可读，等待重新连接；未启动新任务。"; }
        catch (JsonException) { status.Text = "记录正在更新，等待下一次读取。"; }
        catch (Exception e) { status.Text = "读取测试记录失败："+e.Message; }
        finally { reading = false; }
    }
    private void ShowFrame()
    {
        if (root == null || frames.Count == 0 || weatherFolder==null) return;
        var frame = frames[Math.Clamp((int)timeline.Value,0,frames.Count-1)];
        suns.TryGetValue(frame.Utc,out var sun);
        globe.SetWeather(weatherFolder,frame.File,frame.Utc,sun,atmosphere.IsChecked==true);
    }
}
