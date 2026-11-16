using EarthStudio.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EarthStudio.App.UI;

sealed class ProjectView
{
    public Grid Content { get; }=new(){Padding=new Thickness(24),ColumnSpacing=24};
    public event Action? ScanRequested;
    public event Action? FolderRequested;
    public event Action? TimingChanged;
    private readonly TextBox name=new(){Header="项目名称"};
    private readonly TextBlock directory=Ui.Text("",12,true);
    private readonly ProjectTimingView timing=new();
    private readonly SatelliteSelectionView satellites=new();
    private readonly ProductionOptionsView production=new();
    private EarthProject project=new();
    public ProjectView()
    {
        timing.Changed+=()=>TimingChanged?.Invoke();
        Content.ColumnDefinitions.Add(new(){Width=new GridLength(1,GridUnitType.Star)});
        Content.ColumnDefinitions.Add(new(){Width=new GridLength(380)});
        var request=Ui.Column(Ui.Text("2 · 选择制作内容",28),
            Ui.Text("制作一张卫星图片，或制作一段延时时间序列。两种方式都先检查数据，再明确开始下载。",14,true),
            Ui.Card(Ui.Column(name,timing.Content)),Ui.Card(satellites.Content));
        var settings=Ui.Column(Ui.Text("输出与存储",22),production.Content,
            Ui.Card(Ui.Column(Ui.Text("项目数据目录",16),directory,Ui.Button("选择数据目录",()=>FolderRequested?.Invoke()))),
            Ui.Button("下一步：检查所选数据",()=>ScanRequested?.Invoke(),true),
            Ui.Text("第3步复用已有目录记录，只查询新增/失败项。第4步核对容量后才开始制作。素材完成后到第5步预览、运镜和导出Blender。",13,true));
        Content.Children.Add(request);Grid.SetColumn(settings,1);Content.Children.Add(settings);
    }
    public void SetProject(EarthProject value)
    {
        project=value;name.Text=value.Name;timing.Set(value);satellites.Set(value.SatelliteSelection);
        production.Set(value.Production);directory.Text=value.DataDirectory;
    }
    public EarthProject ReadProject()
    {
        var value=timing.Read(project) with {Name=name.Text.Trim(),DataDirectory=directory.Text,
            Production=production.Read(),SatelliteSelection=satellites.Read()};
        _=value.Timeline();return value;
    }
    public void SetMaterialsDirectory(string path)=>project=project with {MaterialsDirectory=path};
    public void SetInventoryDirectory(string path)=>project=project with {InventoryDirectory=path};
    public void SetPipelineDirectory(string path)=>project=project with {PipelineDirectory=path};
    public void SetDirectory(string path)=>directory.Text=path;
    public void Stop() { }
}
