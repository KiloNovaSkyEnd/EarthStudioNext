namespace EarthStudio.Core;

// Saved production intent. Execution support is checked by each engine adapter.
public sealed record ProductionOptions
{
    public string Format { get; init; } = "jpeg";
    public int HimawariDiskSize { get; init; } = 11000;
    public int JpegQuality { get; init; } = 95;
    public int NightLightMetres { get; init; } = 1000;
    // Missing on legacy projects: preserve their serialized production identity.
    [System.Text.Json.Serialization.JsonIgnore(Condition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull)]
    public string? NightMode { get; init; }
    public bool KeepL1 { get; init; }
    public bool KeepIntermediates { get; init; }

    public void Validate()
    {
        if (Format is not ("jpeg" or "png" or "tiff")) throw new ArgumentException("不支持的素材格式。");
        if (HimawariDiskSize is not (11000 or 22000)) throw new ArgumentException("H9圆盘档位必须为11K或22K。");
        if (JpegQuality is < 1 or > 100) throw new ArgumentException("JPEG质量应为1–100。");
        if (NightLightMetres is not (500 or 1000)) throw new ArgumentException("夜景请选择500m或1km。");
        if (NightMode is not (null or "geocolor" or "ai-vis" or "ai-vis-ir")) throw new ArgumentException("夜间模式应为GeoColor、AI-VIS或AI-VIS与红外混合。");
    }
}
