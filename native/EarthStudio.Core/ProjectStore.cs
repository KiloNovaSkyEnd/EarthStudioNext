using System.Text.Json;

namespace EarthStudio.Core;

public sealed class ProjectStore
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    public async Task SaveAsync(string path, EarthProject project, CancellationToken cancellation = default)
    {
        project.Validate(DateTimeOffset.UtcNow);
        _ = project.Timeline();
        var directory = Path.GetDirectoryName(Path.GetFullPath(path))!;
        Directory.CreateDirectory(directory);
        var temp = Path.Combine(directory, $".{Guid.NewGuid():N}.tmp");
        try
        {
            await File.WriteAllTextAsync(temp, JsonSerializer.Serialize(project with { UpdatedUtc = DateTimeOffset.UtcNow }, JsonOptions),cancellation);
            cancellation.ThrowIfCancellationRequested();
            File.Move(temp, path, true);
        }
        finally { if (File.Exists(temp)) File.Delete(temp); }
    }
    public async Task<EarthProject> LoadAsync(string path)
    {
        var info = new FileInfo(path);
        if (info.Length > 1024 * 1024) throw new ArgumentException("项目文件过大。");
        var result = JsonSerializer.Deserialize<EarthProject>(await File.ReadAllTextAsync(path))
            ?? throw new ArgumentException("项目文件为空。");
        result.Validate(DateTimeOffset.UtcNow);
        _ = result.Timeline();
        return result;
    }
}
