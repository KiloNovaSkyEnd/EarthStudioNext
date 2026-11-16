using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;
using EarthStudio.Core;

namespace EarthStudio.App.Services;

// Human-facing exports only. Stable project IDs, asset basenames and draft keys stay unchanged.
static class ReadableNames
{
    public static string Clean(string? value, int limit=48)
    {
        var text=string.Concat((value??"").Normalize().Select(c => char.IsControl(c)||"<>:\"/\\|?*".Contains(c)?'_':c));
        text=Regex.Replace(text,@"\s+"," ").Trim(' ','.');
        if(text.Length>limit)text=text[..limit].TrimEnd(' ','.');
        if(string.IsNullOrEmpty(text))text="未命名项目";
        if(Regex.IsMatch(text,@"^(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])(?:\.|$)",RegexOptions.IgnoreCase))text="_"+text;
        return text;
    }

    public static string ProjectLabel(EarthProject project)
    {
        var mode=project.Production.NightMode switch {"ai-vis"=>"AI-VIS","ai-vis-ir"=>"AI-VIS红外混合",_=>"GeoColor"};
        var first=project.StartUtc.UtcDateTime.ToString("yyyy-MM-dd_HHmm",CultureInfo.InvariantCulture);
        var last=project.EndUtc.UtcDateTime.ToString("yyyy-MM-dd_HHmm",CultureInfo.InvariantCulture);
        return $"{Clean(project.Name,24)}_{first}至{last}_UTC_{mode}";
    }

    public static string MaterialTitle(string folder)
    {
        var name=Path.GetFileName(Path.TrimEndingDirectorySeparator(folder));
        if(!Guid.TryParse(name,out _))return Clean(name,64);
        // Read the material owner's project, not the currently open editing project's name.
        for(var directory=new DirectoryInfo(folder).Parent;directory!=null;directory=directory.Parent)
            if(directory.Name.Equals("queues",StringComparison.OrdinalIgnoreCase) && directory.Parent!=null)
            {
                var file=Path.Combine(directory.Parent.FullName,"project.earthproj");
                try
                {
                    if(File.Exists(file))
                    {
                        using var project=JsonDocument.Parse(File.ReadAllText(file));
                        if(project.RootElement.TryGetProperty("Name",out var title)&&title.ValueKind==JsonValueKind.String&&!string.IsNullOrWhiteSpace(title.GetString()))return Clean(title.GetString(),48);
                    }
                }
                catch(Exception error) when(error is IOException or UnauthorizedAccessException or JsonException) { }
                break;
            }
        return "卫星素材";
    }

    public static string MaterialLabel(string folder)
    {
        // Old UUID delivery directories remain fully supported; use their actual UTC range.
        var name=Path.GetFileName(Path.TrimEndingDirectorySeparator(folder));
        if(!Guid.TryParse(name,out _))return Clean(name,64);
        var manifest=Path.Combine(folder,"manifest.json");
        if(File.Exists(manifest))
        {
            using var document=JsonDocument.Parse(File.ReadAllText(manifest));
            if(document.RootElement.TryGetProperty("frames",out var frames)&&frames.GetArrayLength()>0)
            {
                var first=DateTimeOffset.Parse(frames[0].GetProperty("utc").GetString()!,CultureInfo.InvariantCulture).UtcDateTime;
                var last=DateTimeOffset.Parse(frames[frames.GetArrayLength()-1].GetProperty("utc").GetString()!,CultureInfo.InvariantCulture).UtcDateTime;
                return $"卫星素材_{first:yyyy-MM-dd_HHmm}至{last:yyyy-MM-dd_HHmm}_UTC";
            }
        }
        return "卫星素材";
    }

    public static string AvailablePath(string directory,string label,string extension="")
    {
        var stem=Clean(label,110);
        for(var number=1;number<=10000;number++)
        {
            var candidate=Path.Combine(directory,stem+(number==1?"":$"_第{number:00}版")+extension);
            if(!File.Exists(candidate)&&!Directory.Exists(candidate))return candidate;
        }
        throw new IOException("同名版本过多，请使用新的名称或目录。");
    }
}
