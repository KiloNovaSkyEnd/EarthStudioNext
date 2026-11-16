using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EarthStudio.App.UI;

sealed class UpgradeView
{
    public UIElement Content { get; }
    public UpgradeView()
    {
        var rows=Ui.Column(Ui.Text("Earth Studio Next · 独立开发版",28),
            Ui.Text("新版使用独立配置、账户与输出。旧版代码和素材保留，只读查看；迁移的功能仍需逐项回归。",muted:true),
            Ui.Card(Ui.Column(Ui.Text("已确定的处理约束",20),Ui.Text("Satpy GeoColor · 白天真实海陆 · 夜景1km/500m按需 · 云图JPG为主 · 高细节可选 · 柔和大气/气辉"))),
            Ui.Text("本机 Satpy 配方检查（不等于真实单景或画质通过）",20));
        var file=Path.Combine(AppContext.BaseDirectory,"next_capabilities.json");
        if(File.Exists(file))
        {
            using var audit=JsonDocument.Parse(File.ReadAllText(file));
            rows.Children.Add(Ui.Text("Satpy "+audit.RootElement.GetProperty("satpy_version").GetString()));
            foreach(var source in audit.RootElement.GetProperty("sources").EnumerateArray())
                rows.Children.Add(Ui.Text($"{source.GetProperty("instrument").GetString()}: Reader配置 {(source.GetProperty("reader_config_present").GetBoolean()?"存在":"缺失")} / 原生 GeoColor {(source.GetProperty("stock_geo_color").GetBoolean()?"存在":"无，使用获准兼容路径")}"));
        }
        rows.Children.Add(Ui.Card(Ui.Column(Ui.Text("M4 · 已接入",20),Ui.Text("账户→时间与卫星→目录检查→H9逐时次下载制作；11K JPG＋1km独立夜景、首样验收、逐时次校验与清理。支持暂停继续、保留L1/中间文件，历史输入只读。已有天气序列与多分镜运镜方案保留。"))));
        rows.Children.Add(Ui.Card(Ui.Column(Ui.Text("M5 · JPG动画衔接",20),Ui.Text("已完成区间另存为独立JPG动画包，进入连续天气预览和多分镜运镜；Blender使用原生天气时钟，天气与相机时长独立。轻量播放、暂停细节与最终正式素材分开。"))));
        rows.Children.Add(Ui.Card(Ui.Column(Ui.Text("M5.2 · 单帧与序列",20),Ui.Text("第2步明确选择单帧或序列，统一走预检与制作；第5步显示当前素材与UTC。支持单帧JPG交付、固定天气相机运镜；高级验证工具独立收纳，未接入档位明确标记。"))));
        rows.Children.Add(Ui.Card(Ui.Column(Ui.Text("下一批",20),Ui.Text("静态参考跨时次缓存与并行效率；一键单时次重做审核替换；通用ROI、多星与高细节档位。"))));
        rows.Children.Add(Ui.Text("第4步明确开始后才下载制作；首样验收后按保留设置回收新作业文件。当前是本机开发包，仍依赖Next科学环境、共享参考与Blender；完整安装器另行交付。",12,true));
        Content=Ui.Scroll(rows);
    }
}
