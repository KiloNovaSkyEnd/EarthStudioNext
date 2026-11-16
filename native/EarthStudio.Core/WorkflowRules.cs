namespace EarthStudio.Core;

public static class WorkflowRules
{
    public static string? ProductionBlocker(EarthProject value)
    {
        if(value.SatelliteSelection.Mode!="manual" || !value.SatelliteSelection.Satellites.SequenceEqual(new[]{"himawari9"}))
            return "当前可检查所选卫星目录；正式制作暂仅接通向日葵9号单星，多星/全球制作待接入。";
        var p=value.Production;
        if(p.NightMode is "ai-vis" or "ai-vis-ir" && p.NightLightMetres!=1000)
            return "新增AI夜间模式当前要求1km独立夜景；500m夜景尚待该模式资格验证。默认GeoColor仍支持500m。";
        if(p.Format!="jpeg" || p.HimawariDiskSize!=11000 || p.NightLightMetres is not (500 or 1000))
            return "此档位已保存，但尚未接通制作。当前可用：H9、11K JPG、500m/1km独立夜景；PNG/TIFF与22K云图待接入。";
        return null;
    }
    public static bool SameCatalog(EarthProject a,EarthProject b)=>
        (a.Production.NightMode??"geocolor")== (b.Production.NightMode??"geocolor") &&
        a.Id==b.Id && a.CaptureMode==b.CaptureMode && a.StartUtc==b.StartUtc && a.EndUtc==b.EndUtc &&
        a.IntervalMinutes==b.IntervalMinutes && a.Scope==b.Scope && a.Recipe==b.Recipe &&
        a.SatelliteSelection.Mode==b.SatelliteSelection.Mode && a.SatelliteSelection.Preset==b.SatelliteSelection.Preset &&
        a.SatelliteSelection.Satellites.SequenceEqual(b.SatelliteSelection.Satellites);
    public static bool SameProduction(EarthProject a,EarthProject b)=>SameCatalog(a,b) &&
        a.Production==b.Production && string.Equals(Path.GetFullPath(a.DataDirectory),Path.GetFullPath(b.DataDirectory),StringComparison.OrdinalIgnoreCase);
}
