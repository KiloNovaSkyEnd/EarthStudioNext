using System.Text.Json;
using System.Security.Cryptography;
using System.Text;

namespace EarthStudio.App.Services;

sealed class WorkspaceDocumentStore
{
    private readonly SemaphoreSlim draftLock = new(1, 1);
    private static string DraftPath(string materials, Guid projectId)
    {
        var key = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(projectId.ToString("N") + ":" + Path.GetFullPath(materials).ToUpperInvariant())));
        return Path.Combine(AppPaths.UserData, "WorkspaceDrafts", key + ".json");
    }
    public async Task<string?> ReadDraftAsync(string materials, Guid projectId)
    {
        var path = DraftPath(materials, projectId);
        return File.Exists(path) ? await File.ReadAllTextAsync(path) : null;
    }
    public async Task SaveDraftAsync(string materials, Guid projectId, JsonElement data)
    {
        if (data.GetProperty("schema").GetString() != "earthstudio.timeline.v1") throw new ArgumentException("草稿格式错误。");
        await draftLock.WaitAsync();
        var path = DraftPath(materials, projectId); var temp = path + ".tmp";
        try { Directory.CreateDirectory(Path.GetDirectoryName(path)!); await File.WriteAllTextAsync(temp, data.GetRawText()); File.Move(temp, path, true); }
        finally { if (File.Exists(temp)) File.Delete(temp); draftLock.Release(); }
    }
    public async Task<string> SaveAsync(string type, JsonElement data)
    {
        var schema = data.GetProperty("schema").GetString();
        var plan = type == "plan-export";
        var renderPlan=type=="render-plan-export";
        if (renderPlan ? schema != "earthstudio.render_plan.v1" : plan ? schema is not ("earthstudio.timeline.v1" or "earthstudio.frame_mapping.v1") : schema is not ("earthstudio.camera_bundle.v1" or "earthstudio.camera.v1"))
            throw new ArgumentException("摄影棚导出格式不受支持。");
        var directory = Path.Combine(AppPaths.UserData, renderPlan ? "RenderPlans" : plan ? "ShotPlans" : "CameraExports");
        AppPaths.RequireWritable(directory); Directory.CreateDirectory(directory);
        var label=renderPlan?"渲染任务":plan?"运镜工程":"相机导出";
        var path = ReadableNames.AvailablePath(directory,$"{label}_{DateTime.UtcNow:yyyy-MM-dd_HH-mm-ss}_UTC",".json");
        var temp = path + ".tmp";
        try { await File.WriteAllTextAsync(temp, data.GetRawText()); File.Move(temp, path); }
        finally { if (File.Exists(temp)) File.Delete(temp); }
        return path;
    }
}
