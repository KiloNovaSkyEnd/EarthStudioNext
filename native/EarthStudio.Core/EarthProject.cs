namespace EarthStudio.Core;

public sealed record EarthProject
{
    public int SchemaVersion { get; init; } = 1;
    public Guid Id { get; init; } = Guid.NewGuid();
    public string CaptureMode { get; init; } = "sequence";
    public string Name { get; init; } = "新的地球项目";
    public DateTimeOffset StartUtc { get; init; } = new(2020, 10, 29, 16, 0, 0, TimeSpan.Zero);
    public DateTimeOffset EndUtc { get; init; } = new(2020, 10, 29, 17, 0, 0, TimeSpan.Zero);
    public int IntervalMinutes { get; init; } = 30;
    public string Scope { get; init; } = "global-nonpolar";
    public string Recipe { get; init; } = "geocolor-style";
    public string DataDirectory { get; init; } = "";
    public string? MaterialsDirectory { get; init; }
    public string? InventoryDirectory { get; init; }
    public string? PipelineDirectory { get; init; }
    public ProductionOptions Production { get; init; } = new();
    public SatelliteSelection SatelliteSelection { get; init; } = new();
    public DateTimeOffset UpdatedUtc { get; init; } = DateTimeOffset.UtcNow;

    public void Validate(DateTimeOffset now)
    {
        if (SchemaVersion != 1) throw new ArgumentException("项目格式版本不受支持。");
        if (string.IsNullOrWhiteSpace(Name) || Name.Length > 100) throw new ArgumentException("项目名须为1–100个字符。");
        if (StartUtc.Offset != TimeSpan.Zero || EndUtc.Offset != TimeSpan.Zero) throw new ArgumentException("项目时间必须为 UTC。");
        if (StartUtc < new DateTimeOffset(2018, 1, 1, 0, 0, 0, TimeSpan.Zero)) throw new ArgumentException("目前项目范围从2018年开始。");
        if (CaptureMode is not ("single" or "sequence")) throw new ArgumentException("请选择单帧或时间序列制作。");
        if (CaptureMode == "single" && EndUtc != StartUtc) throw new ArgumentException("单帧项目只使用一个UTC时次。");
        if (CaptureMode == "sequence" && EndUtc <= StartUtc) throw new ArgumentException("结束时间必须晚于开始时间。");
        if (EndUtc > now) throw new ArgumentException("结束时间不能晚于当前 UTC。");
        if (IntervalMinutes is not (10 or 15 or 30 or 60)) throw new ArgumentException("时间间隔应为10、15、30或60分钟。");
        if (Scope != "global-nonpolar" || Recipe != "geocolor-style") throw new ArgumentException("此版本只支持非极地全球 GeoColor 风格项目。");
        if (string.IsNullOrWhiteSpace(DataDirectory) || !Path.IsPathFullyQualified(DataDirectory)) throw new ArgumentException("请选择绝对数据目录。");
        if (MaterialsDirectory != null && !Path.IsPathFullyQualified(MaterialsDirectory)) throw new ArgumentException("素材目录必须为绝对路径。");
        if (InventoryDirectory != null && !Path.IsPathFullyQualified(InventoryDirectory)) throw new ArgumentException("检查记录目录必须为绝对路径。");
        if (PipelineDirectory != null && !Path.IsPathFullyQualified(PipelineDirectory)) throw new ArgumentException("队列目录必须为绝对路径。");
        if (Production == null) throw new ArgumentException("缺少素材配置。");
        Production.Validate();
        if (SatelliteSelection == null) throw new ArgumentException("缺少卫星选择设置。");
        SatelliteSelection.Validate();
    }

    public IReadOnlyList<DateTimeOffset> Timeline()
    {
        Validate(DateTimeOffset.UtcNow);
        var count = (EndUtc - StartUtc).TotalMinutes / IntervalMinutes;
        if (count > 10000) throw new ArgumentException("一个基础版项目最多10001个时间点，请拆分时间段。");
        var times = new List<DateTimeOffset>();
        for (var time = StartUtc; time <= EndUtc; time = time.AddMinutes(IntervalMinutes)) times.Add(time);
        return times;
    }
}
