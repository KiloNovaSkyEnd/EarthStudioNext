using EarthStudio.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EarthStudio.App.UI;

sealed class SatelliteSelectionView
{
    public UIElement Content { get; }
    private readonly ComboBox mode=new() { Header="搜索使用的卫星" };
    private readonly Dictionary<string,CheckBox> choices=new();
    private readonly StackPanel list=new() { Spacing=6 };
    private bool setting;
    private bool needsScopeReview;
    public SatelliteSelectionView()
    {
        mode.Items.Add("单星或自选多星 · 只查勾选项");mode.Items.Add("全球预设 · 按日期查各区域候选");
        foreach(var item in SatelliteSelection.Choices) {
            var box=new CheckBox { Content=Ui.Text(item.Value,13) };choices.Add(item.Key,box);list.Children.Add(box);
        }
        Content=Ui.Column(Ui.Text("先选卫星，再搜索",18),mode,
            Ui.Button("预设：向日葵9号全圆盘",()=>Pick(new[]{"himawari9"})),
            Ui.Button("预设：全球多星覆盖候选",()=> { mode.SelectedIndex=1;needsScopeReview=false; }),
            Ui.Button("全选列表",()=>Pick(choices.Keys)),Ui.Button("清空勾选",()=>Pick(Array.Empty<string>())),list,
            Ui.Text("单星圆盘只覆盖该星可见半球。全球预设检查亚太、美洲东/西、欧洲非洲和印度洋5个方向；实际平台和覆盖仍须核验，多星拼接生产待接入。",12,true));
        mode.SelectionChanged+=(_,_)=> { foreach(var box in choices.Values) box.IsEnabled=mode.SelectedIndex==0;if(!setting)needsScopeReview=false; };
        Set(new());
    }
    private void Pick(IEnumerable<string> ids)
    {
        var selected=ids.ToHashSet();mode.SelectedIndex=0;
        if(!setting)needsScopeReview=false;
        foreach(var item in choices) item.Value.IsChecked=selected.Contains(item.Key);
    }
    public void Set(SatelliteSelection value)
    {
        setting=true;
        try { Pick(value.Satellites);mode.SelectedIndex=value.Mode=="auto"?1:0;needsScopeReview=value.Mode=="auto"&&value.Preset!="global"; }
        finally { setting=false; }
    }
    public SatelliteSelection Read()
    {
        if(needsScopeReview)throw new ArgumentException("此旧项目没有明确的卫星预设。请先点“向日葵9号全圆盘”或“全球多星覆盖候选”，再搜索；不会默认搜索全球。");
        var ids=choices.Where(item=>item.Value.IsChecked==true).Select(item=>item.Key).ToArray();
        var value=new SatelliteSelection { Mode=mode.SelectedIndex==1?"auto":"manual",Preset=mode.SelectedIndex==1?"global":ids.SequenceEqual(new[]{"himawari9"})?"h9":"custom",Satellites=ids };
        value.Validate();return value;
    }
}
