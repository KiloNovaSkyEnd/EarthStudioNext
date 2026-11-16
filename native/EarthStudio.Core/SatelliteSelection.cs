namespace EarthStudio.Core;

public sealed record SatelliteSelection
{
    public string Mode { get; init; } = "auto";
    public string Preset { get; init; } = "unspecified";
    public string[] Satellites { get; init; } = Array.Empty<string>();
    public static IReadOnlyDictionary<string,string> Choices { get; } = new Dictionary<string,string> {
        ["himawari9"]="向日葵9号 · 亚太", ["himawari8"]="向日葵8号 · 历史亚太",
        ["goes19"]="GOES-19 · 美洲东部", ["goes18"]="GOES-18 · 美洲西部",
        ["goes16"]="GOES-16 · 历史/备用", ["goes17"]="GOES-17 · 历史/备用",
        ["meteosat12"]="Meteosat-12 · 欧洲非洲（适配待完成）",
        ["meteosat_zero"]="Meteosat历史欧洲非洲槽位 · 平台需核验",
        ["meteosat_iodc"]="Meteosat印度洋槽位 · 平台需核验" };
    public void Validate()
    {
        if (Mode is not ("auto" or "manual")) throw new ArgumentException("请选择自动推荐或手动选择卫星。");
        if (Preset is not ("unspecified" or "custom" or "h9" or "global")) throw new ArgumentException("未知卫星预设。");
        if (Satellites == null || Satellites.Any(id=>!Choices.ContainsKey(id)) || Satellites.Distinct().Count()!=Satellites.Length)
            throw new ArgumentException("卫星选择包含未知或重复项目。");
        if (Mode=="manual" && Satellites.Length==0) throw new ArgumentException("搜索前请至少勾选一颗卫星。");
    }
    public void ValidateSearchScope()
    {
        Validate();
        if(Mode=="auto" && Preset!="global") throw new ArgumentException("请先选择单星、自选多星或全球预设；不会默认搜索全球。");
    }
}
