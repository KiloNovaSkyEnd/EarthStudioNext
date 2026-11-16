using EarthStudio.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EarthStudio.App.UI;

sealed class ProductionOptionsView
{
    public UIElement Content { get; }
    private readonly ComboBox format = new() { Header = "正式素材格式" };
    private readonly ComboBox size = new() { Header = "H9圆盘尺寸" };
    private readonly NumberBox quality = new() { Header = "JPEG质量", Minimum = 1, Maximum = 100, Value = 95, SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Compact };
    private readonly ComboBox night = new() { Header = "地面夜景分辨率" };
    private readonly ComboBox nightMode = new() { Header = "夜间云图处理" };
    private readonly CheckBox keepL1 = new() { Content = "保留L1" };
    private readonly CheckBox keepTemporary = new() { Content = "保留中间文件" };

    public ProductionOptionsView()
    {
        foreach (var text in new[] { "JPG · 日常延时", "PNG · 无损（制作待接入）", "TIFF · 无损/地理素材（制作待接入）" }) format.Items.Add(text);
        foreach (var text in new[] { "11000 × 11000", "22000 × 22000（制作待接入）" }) size.Items.Add(text);
        foreach (var text in new[] { "1 km", "500 m" }) night.Items.Add(text);
        foreach (var text in new[] { "默认 Satpy GeoColor", "纯 AI-VIS 夜间", "AI-VIS＋红外混合 V9 夜间" }) nightMode.Items.Add(text);
        Content = Ui.Column(Ui.Text("素材制作设置", 20), format, size, quality, nightMode, night, keepL1, keepTemporary,
            Ui.Text("AI模式使用卫星红外估计夜间可见光外观；白天沿用标准GeoColor。需要额外红外波段和GPU。目前新增模式使用1km独立夜景。",12,true),
            Ui.Text("当前单帧与序列均可制作H9 11K JPG＋500m/1km夜景。其他档位可保存需求，暂不能启动制作；不会自动替换成低档位。", 12, true));
        Set(new());
    }

    public void Set(ProductionOptions value)
    {
        format.SelectedIndex = Array.IndexOf(new[] { "jpeg", "png", "tiff" }, value.Format);
        size.SelectedIndex = value.HimawariDiskSize == 22000 ? 1 : 0;
        quality.Value = value.JpegQuality;
        night.SelectedIndex = value.NightLightMetres == 500 ? 1 : 0;
        nightMode.SelectedIndex = value.NightMode == "ai-vis" ? 1 : value.NightMode == "ai-vis-ir" ? 2 : 0;
        keepL1.IsChecked = value.KeepL1; keepTemporary.IsChecked = value.KeepIntermediates;
    }

    public ProductionOptions Read()
    {
        if (!double.IsFinite(quality.Value) || quality.Value != Math.Truncate(quality.Value)) throw new ArgumentException("JPEG质量请输入整数。");
        var result = new ProductionOptions { Format = new[] { "jpeg", "png", "tiff" }[Math.Max(0, format.SelectedIndex)],
            HimawariDiskSize = size.SelectedIndex == 1 ? 22000 : 11000, JpegQuality = (int)quality.Value,
            NightMode = nightMode.SelectedIndex == 1 ? "ai-vis" : nightMode.SelectedIndex == 2 ? "ai-vis-ir" : null,
            NightLightMetres = night.SelectedIndex == 1 ? 500 : 1000, KeepL1 = keepL1.IsChecked == true, KeepIntermediates = keepTemporary.IsChecked == true };
        result.Validate(); return result;
    }
}
