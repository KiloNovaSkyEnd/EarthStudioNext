using System.Text.Json;
using System.Diagnostics;
using Microsoft.UI.Xaml.Controls;

namespace EarthStudio.App.UI;

sealed class TasksView
{
    public Microsoft.UI.Xaml.UIElement Content { get; }
    public event Action? ImportRequested;
    public event Action? ImportFileRequested;
    private readonly List<JsonElement> records=new();
    private readonly TextBlock range=Ui.Text("",13,true),pageInfo=Ui.Text("",13,true);
    private readonly Button older,newer;
    private int page;
    public void SetRange(string text)=>range.Text=text;
    public void SetSelectionChanged(bool changed,bool active)=>range.Text=range.Text.Split("\n当前编辑设置")[0]+(changed?"\n当前编辑设置已改变；"+(active?"日期修改后查询自动切换到新范围。":"按新范围继续检查。")+"重叠项会复用。":"");
    public event Action? ContinueRequested;
    public event Action? ResumeRequested;
    public event Action? RefreshRequested;
    private readonly StackPanel entries = new() { Spacing = 8 };
    private readonly ProgressBar progress = new() { Minimum = 0, Maximum = 1 };
    private readonly TextBlock summary = Ui.Text("尚未开始检查数据", 16);
    private readonly Button next;
    private string? outputDirectory;
    public TasksView()
    {
        older=Ui.Button("更早记录 →",()=>{page++;RenderPage();});
        newer=Ui.Button("← 更新记录",()=>{page=Math.Max(0,page-1);RenderPage();});
        next=Ui.Button("下一步：核对制作计划",()=>ContinueRequested?.Invoke());next.IsEnabled=false;
        Content = Ui.Scroll(Ui.Column(Ui.Text("3 · 检查数据与容量", 28),
            Ui.Text("按项目中选定的卫星检查真实存档；自动推荐模式按日期覆盖各区域。这里只查询目录，不下载卫星素材。", muted: true),
            Ui.Text("已查到的重叠时次自动复用；仅查询新增或失败的项目。目录记录不等于素材已下载。",13,true),
            range,Ui.Button("导入其他位置的inventory.json文件",()=>ImportFileRequested?.Invoke()),
            Ui.Button("从其他位置的文件夹导入检查记录",()=>ImportRequested?.Invoke()),
            Ui.Column(Ui.Button("继续检查 / 复用已有记录",()=>ResumeRequested?.Invoke()),
                Ui.Button("强制刷新当前范围",()=>RefreshRequested?.Invoke())),
            Ui.Card(Ui.Column(summary, progress, Ui.Button("打开本次检查记录", () =>
            {
                if (outputDirectory != null && Directory.Exists(outputDirectory))
                    Process.Start(new ProcessStartInfo(outputDirectory) { UseShellExecute = true });
            }))),next,
            Ui.Text("本页只做目录预检。下一步生成H9制作计划，核对后才下载；多星生产适配尚未接入。",13,true),Ui.Column(pageInfo,newer,older),entries));
    }
    public void Reset() { records.Clear();page=0;entries.Children.Clear();UpdatePager(); progress.Value = 0; summary.Text = "正在连接数据目录…";next.IsEnabled=false; }
    public void Ready(){next.IsEnabled=true;summary.Text+=" · 检查完成，可进入制作计划";}
    public void Restore(JsonElement data)
    {
        Reset();
        var records=data.GetProperty("records");var total=data.GetProperty("expected_records").GetInt32();
        foreach(var record in records.EnumerateArray())this.records.Add(record.Clone());
        progress.Maximum=total;progress.Value=this.records.Count;RenderPage();
        var count=this.records.Count;
        summary.Text=$"已恢复 {count} / {total} 项检查记录；继续时自动复用重叠部分";
        if(data.GetProperty("finished").GetBoolean())Ready();
    }
    public void SetOutput(string path) => outputDirectory = path;
    public void Accept(JsonElement message)
    {
        if (message.GetProperty("type").GetString() == "progress")
        {
            var count = message.GetProperty("completed").GetInt32();
            var total = message.GetProperty("total").GetInt32();
            progress.Maximum = total; progress.Value = count;
            var record = message.GetProperty("record");records.Add(record.Clone());
            summary.Text=$"已检查 {count} / {total} 个卫星/区域与时间组合";
            if(page==0){entries.Children.Insert(0,Card(record));if(entries.Children.Count>100)entries.Children.RemoveAt(100);}
            UpdatePager();
        }
    }
    private Microsoft.UI.Xaml.UIElement Card(JsonElement record)
    {
            var state = record.GetProperty("state").GetString();
            var available = state == "available";
            var detail = record.TryGetProperty("quality",out var quality) ? quality.GetString() :
                state == "missing" ? "所选卫星在该时间窗口未找到完整目录记录" : "请求或适配未完成，尚不能判断数据是否可用";
            var cached=record.TryGetProperty("cache_hit",out var hit) && hit.GetBoolean();
            var label=state switch { "available"=>"发现目录", "missing"=>"未找到完整目录", "not-applicable"=>"日期不适用", _=>"待核验" };
            return Ui.Card(Ui.Column(
                Ui.Text($"{record.GetProperty("region").GetString()} · {label}{(cached ? " · 复用记录" : "")}"),
                Ui.Text($"{record.GetProperty("requested_utc").GetString()}  |  {detail}", 12, true)), new(14));
    }
    private void UpdatePager()
    {
        var pages=EarthStudio.Core.CatalogPages.Count(records.Count);page=Math.Clamp(page,0,pages-1);
        pageInfo.Text=$"共 {records.Count} 条记录 · 第 {page+1} / {pages} 页 · 每页最多100条，所有记录均可翻页查看";
        newer.IsEnabled=page>0;older.IsEnabled=(page+1)*100<records.Count;
    }
    private void RenderPage()
    {
        UpdatePager();entries.Children.Clear();
        foreach(var index in EarthStudio.Core.CatalogPages.Indices(records.Count,page))entries.Children.Add(Card(records[index]));
    }
}
