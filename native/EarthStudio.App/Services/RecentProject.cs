using System.Text.Json;

namespace EarthStudio.App.Services;

static class RecentProject
{
    private static string FilePath=>Path.Combine(AppPaths.UserData,"recent_project.json");
    public static string? Read()
    {
        if(!File.Exists(FilePath))return null;
        using var document=JsonDocument.Parse(AtomicJsonFile.Read(FilePath));
        return document.RootElement.TryGetProperty("path",out var value)&&value.ValueKind==JsonValueKind.String?value.GetString():null;
    }
    public static void Save(string? path)
    {
        Directory.CreateDirectory(AppPaths.UserData);
        AtomicJsonFile.Write(FilePath,JsonSerializer.Serialize(new {path}));
    }
}
