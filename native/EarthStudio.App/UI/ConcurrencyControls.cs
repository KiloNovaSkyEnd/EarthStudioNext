using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EarthStudio.App.UI;

sealed class ConcurrencyControls
{
    private readonly ComboBox mode=new(){Header="处理并行模式",ItemsSource=new[]{"自动：按实测建议和实际负载","手动：设置目标并行数","串行：一次处理一张"},SelectedIndex=0};
    private readonly NumberBox count=new(){Header="同时制作目标（张）",Minimum=1,Maximum=8,Value=4,SmallChange=1,SpinButtonPlacementMode=NumberBoxSpinButtonPlacementMode.Inline};
    private readonly NumberBox prefetch=new(){Header="提前下载 / 等待的时次数",Minimum=1,Maximum=8,Value=3,SmallChange=1,SpinButtonPlacementMode=NumberBoxSpinButtonPlacementMode.Inline};
    private readonly ComboBox verification=new(){Header="成果校验方式",ItemsSource=new[]{"严格：每帧重开Blender","标准批量：逐帧图片检查＋Blender抽检"},SelectedIndex=0};
    private readonly NumberBox interval=new(){Header="Blender抽检间隔（帧）",Minimum=1,Maximum=100,Value=50,SmallChange=1,IsEnabled=false,SpinButtonPlacementMode=NumberBoxSpinButtonPlacementMode.Inline};
    public UIElement Content {get;}
    public bool Parallel=>mode.SelectedIndex!=2;
    public string Control=>mode.SelectedIndex==1?"manual":"auto";
    public int Target=>mode.SelectedIndex==1?Read(count):8;
    public int Prefetch=>Read(prefetch);
    public string VerificationMode=>verification.SelectedIndex==1?"batch":"strict";
    public int SampleInterval=>double.IsNaN(interval.Value)||interval.Value!=Math.Truncate(interval.Value)||interval.Value<1||interval.Value>100
        ?throw new ArgumentException("抽检间隔请输入1–100帧的整数。"):(int)interval.Value;
    public event Action? ApplyRequested;
    public ConcurrencyControls()
    {
        count.IsEnabled=false;
        mode.SelectionChanged+=(_,_)=>count.IsEnabled=mode.SelectedIndex==1;
        verification.SelectionChanged+=(_,_)=>interval.IsEnabled=verification.SelectedIndex==1;
        Content=Ui.Card(Ui.Column(mode,count,prefetch,verification,interval,
            Ui.Text("标准批量仍完整检查每帧图片、遮罩、UTC与依赖；首个新模板、固定间隔、缺档边界及最终动画重开Blender。未抽检帧不会标为已在Blender逐帧打开。500m夜景暂保持严格校验。",13,true),
            Ui.Text("自动模式根据实际负载和内存峰值调整；制作与独立校验分别计预算。手动数值是制作目标，校验另行排队；资源不足时等待。降低目标会让已开始的时次正常完成。",13,true),
            Ui.Button("应用并行设置（运行中也可调整）",()=>ApplyRequested?.Invoke())));
    }
    private static int Read(NumberBox box)
    {
        if(double.IsNaN(box.Value)||box.Value!=Math.Truncate(box.Value)||box.Value<1||box.Value>8)
            throw new ArgumentException("并行与预取数量请输入1–8的整数。");
        return (int)box.Value;
    }
    public void Load(string control,int maximum,int ahead,bool parallel)
    {
        count.Value=maximum;prefetch.Value=ahead;mode.SelectedIndex=parallel?(control=="manual"?1:0):2;
    }
    public void LoadVerification(string value,int every){verification.SelectedIndex=value=="batch"?1:0;interval.Value=every;}
}
