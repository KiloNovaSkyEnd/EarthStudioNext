using Microsoft.UI.Xaml.Controls;
using System.Diagnostics;
using System.Text.Json;

namespace EarthStudio.App.UI;

sealed class ProductionView
{
    public ScrollViewer Content { get; }
    public event Action<string>? StartRequested;
    public event Action<string,string>? DeliveryRequested;
    private readonly TextBox utc = new() { Header = "制作一个真实时次 · UTC", Text = "2026-10-20T13:00:00Z" };
    private readonly TextBlock status = Ui.Text("等待开始", 13, true);
    private readonly Button start;
    private readonly TextBox package = new() { Header="已提交素材目录" };
    private readonly CheckBox accepted = new() { Content="我已检查此JPG档位的画质，同意按校验清单清理新作业输入" };
    private readonly Button build;
    private readonly Button plan;
    private readonly Button cleanup;
    private readonly Button open;
    public ProductionView()
    {
        start=Ui.Button("制作此时次的JPG分层素材", () => StartRequested?.Invoke(utc.Text.Trim()), true);
        build=Ui.Button("生成Blender并重新打开校验",()=>DeliveryRequested?.Invoke(package.Text.Trim(),"blender"));
        open=Ui.Button("打开此Blender工程",()=> {
            var path=Path.Combine(package.Text.Trim(),"EarthStudio_JPEG_独立灯光.blend");
            if (!File.Exists(path)) { Report("请先生成Blender工程。");return; }
            var launch=new ProcessStartInfo(AppPaths.BlenderExecutable) { UseShellExecute=false };
            launch.ArgumentList.Add(path);launch.ArgumentList.Add("--disable-autoexec");Process.Start(launch);
        });
        plan=Ui.Button("查看逐时次清理清单",()=> { if (accepted.IsChecked==true) DeliveryRequested?.Invoke(package.Text.Trim(),"plan"); else Report("请先检查Blender画面并勾选质量验收。"); });
        cleanup=Ui.Button("按校验清单清理此时次",()=> { if (accepted.IsChecked==true) DeliveryRequested?.Invoke(package.Text.Trim(),"cleanup"); else Report("尚未确认画质，不执行清理。"); });
        Content=Ui.Scroll(Ui.Column(Ui.Text("高级工具 · 本机已有L1试制", 26),
            Ui.Text("使用本机已有向日葵9号数据，不下载。采用项目中的JPG质量；当前接通11K＋1km夜景。",14,true),
            Ui.Text("正常的单帧制作请到第2步选择“单帧图片”，再走第3、4步。此工具仅用于已有L1的开发验证，不代替正常下载与制作流程。",13,true),
            utc,start,status,package,build,open,accepted,plan,cleanup,
            Ui.Text("颜色以JPG保存，支持区和灯光传输用无损标量遮罩。灯光、蓝色大气、气辉分别控制。新分层方案须经Blender重开与画面验收后才进入清理；历史数据保持只读。",13,true)));
    }
    public void SetBusy(bool busy) { start.IsEnabled=!busy;utc.IsEnabled=!busy;build.IsEnabled=!busy;open.IsEnabled=!busy;plan.IsEnabled=!busy;cleanup.IsEnabled=!busy;package.IsEnabled=!busy;accepted.IsEnabled=!busy; }
    public void SetPackage(string path) { package.Text=path;accepted.IsChecked=false; }
    public void Report(string value)
    {
        try {
            using var json=JsonDocument.Parse(value);var data=json.RootElement;
            if (data.TryGetProperty("candidates",out var candidates)) {
                var items=candidates.EnumerateArray().ToArray();
                var bytes=items.Sum(item=>item.GetProperty("stamp").GetProperty("bytes").GetInt64());
                status.Text=$"可清理 {items.Length} 个新作业文件，逻辑体积 {bytes/1048576.0:F1} MB。\n"+
                    string.Join("\n",items.Take(12).Select(item=>item.GetProperty("path").GetString()))+
                    "\n完整清单保存在素材目录 cleanup_plan.json。历史数据和仍被引用的文件保留。";return;
            }
            if (data.TryGetProperty("deleted_files",out var deleted)) { status.Text=$"已按清单清理 {deleted.GetInt32()} 个新作业文件。正式素材、Blender工程和共享参考保留。";return; }
            if (data.TryGetProperty("phase",out var phase)) {
                status.Text=phase.GetString() switch {
                    "verifying-and-decoding-inputs"=>"正在校验并解码本机数据…",
                    "reading-h9-bands"=>"正在读取H9所需波段…",
                    "planning-stock"=>"准备原生GeoColor配方…",
                    "planning-independent-ground"=>"准备独立地面夜景分层…",
                    "computing-stock-and-layers"=>"计算云图与独立夜景层；完成后再编码…",
                    "encoding-jpeg-and-lossless-masks"=>"制作JPG与必要的无损遮罩…",
                    "committed-awaiting-blender-verification"=>"素材已提交，等待Blender校验。",
                    "blender-build"=>"正在生成独立灯光Blender工程…",
                    "blender-reopen"=>"正在重新打开Blender校验依赖与参数…",
                    "verified-awaiting-user-quality-acceptance"=>"Blender重开校验通过。请打开工程检查画质，再查看清理清单。",
                    _=>value };return;
            }
        } catch (JsonException) { }
        status.Text=value;
    }
}
