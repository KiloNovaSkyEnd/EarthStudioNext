using EarthStudio.Core;
using EarthStudio.App.Services;
using System.Text.Json;

namespace EarthStudio.App;

sealed partial class MainWindow
{
    private EarthProject? inventoryProject,catalogSnapshot;
    private readonly LiveCatalogRequest liveCatalog=new();
    private EarthProject ReadCatalogSelection()
    {
        var value=project.ReadProject();value.SatelliteSelection.ValidateSearchScope();_=value.Timeline();
        AppPaths.RequireWritable(value.DataDirectory);return value;
    }
    private void UpdateLiveCatalog()
    {
        if(!liveCatalog.IsRunning)return;
        try
        {
            if(!liveCatalog.Request(ReadCatalogSelection()))return;
            lastInventory=null;inventoryProject=null;tasks.Reset();
            tasks.SetRange("正在切换到新的日期范围；重叠记录复用，范围外记录保留在缓存。");
            pipeline.SetReadiness(false,"日期范围更新中，请等待最新范围检查完成。");
            status.Text="正在更新查询范围；不需要手动取消或重新开始。";
        }
        catch(ArgumentException error){status.Text="请完成有效日期范围后自动更新："+error.Message;}
    }
    private async Task ScanCatalogAsync(bool refresh)
    {
        if(liveCatalog.IsRunning){liveCatalog.Request(ReadCatalogSelection(),refresh);return;}
        var value=ReadCatalogSelection();
        var operation=background.Begin(BackgroundLane.Catalog);RefreshCancelButton();accounts.SetBusy(true);
        SelectPage("tasks");
        try {await liveCatalog.RunAsync(value,refresh,ScanCatalogRangeAsync,operation.Token);}
        finally {operation.Dispose();catalogSnapshot=null;RefreshCancelButton();accounts.SetBusy(false);RefreshWorkflow();}
    }
    private async Task ScanCatalogRangeAsync(EarthProject value,bool refresh,CancellationToken token)
    {
        // Coalesce rapid date/time picker changes before launching a replacement process.
        await Task.Delay(350,token);
        var folder=Path.Combine(value.DataDirectory,"projects",value.Id.ToString("N"));
        var output=Path.Combine(folder,"inventories",DateTimeOffset.UtcNow.ToString("yyyyMMddTHHmmssZ")+"_"+Guid.NewGuid().ToString("N")[..8]);
        value=value with {InventoryDirectory=output};
        await store.SaveAsync(Path.Combine(folder,"project.earthproj"),value,token);
        if(projectFile!=null)await store.SaveAsync(projectFile,value,token);
        token.ThrowIfCancellationRequested();project.SetInventoryDirectory(output);
        catalogSnapshot=value;tasks.Reset();tasks.SetRange($"当前查询：{value.StartUtc:u} → {value.EndUtc:u} · {string.Join(", ",value.SatelliteSelection.Satellites)}\n修改日期会自动更新；仅查询未缓存时次。");tasks.SetOutput(output);lastInventory=null;inventoryProject=null;
        await engine.RunAsync(new {action="scan",project=value,options=new {output,refresh}},message=>
        {
            if(token.IsCancellationRequested)return;
            tasks.Accept(message);
            if(message.TryGetProperty("message",out var text))status.Text=text.GetString()??"";
        },token);
        token.ThrowIfCancellationRequested();
        await RestoreCatalogAsync(value,token);RefreshWorkflow();
    }

    private async Task ImportCatalogAsync(string source)
    {
        await RunAsync(new {action="import-catalog",options=new {source}});
        if(File.Exists(source))
        {
            using var document=JsonDocument.Parse(await File.ReadAllTextAsync(source));
            if(!document.RootElement.TryGetProperty("records",out _))throw new ArgumentException("请选择目录检查的inventory.json。");
            tasks.SetOutput(Path.GetDirectoryName(source)!);tasks.Restore(document.RootElement);
            tasks.SetRange("外部检查记录："+source+"\n可以翻页查看全部记录；按当前设置继续检查以生成本项目计划，重叠时次会自动复用。");
            SelectPage("tasks");
        }
    }
    private async Task SaveWorkingProjectAsync()
    {
        var value=project.ReadProject();
        await store.SaveAsync(Path.Combine(value.DataDirectory,"projects",value.Id.ToString("N"),"project.earthproj"),value);
        if(projectFile!=null)await store.SaveAsync(projectFile,value);
        RecentProject.Save(projectFile??Path.Combine(value.DataDirectory,"projects",value.Id.ToString("N"),"project.earthproj"));
    }
    private async Task RestoreCatalogAsync(EarthProject value,CancellationToken token=default)
    {
        var directory=value.InventoryDirectory;
        // Projects created before the pointer existed can recover their last scan.
        if(directory==null)
        {
            var root=Path.Combine(value.DataDirectory,"projects",value.Id.ToString("N"),"inventories");
            if(Directory.Exists(root))directory=Directory.EnumerateDirectories(root).OrderByDescending(Path.GetFileName).FirstOrDefault();
        }
        if(directory==null)return;
        var path=Path.Combine(directory,"inventory.json");if(!File.Exists(path))return;
        try
        {
            using var data=JsonDocument.Parse(await File.ReadAllTextAsync(path,token));
            token.ThrowIfCancellationRequested();
            if(!data.RootElement.TryGetProperty("project_spec",out var projectSpec))return;
            var spec=projectSpec.Deserialize<EarthProject>();
            if(spec==null || !WorkflowRules.SameCatalog(spec,value))return;
            project.SetInventoryDirectory(directory);tasks.SetOutput(directory);tasks.Restore(data.RootElement);
            tasks.SetRange($"记录范围：{spec.StartUtc:u} → {spec.EndUtc:u}");
            inventoryProject=spec;
            lastInventory=data.RootElement.GetProperty("finished").GetBoolean()?path:null;
        }
        catch(JsonException) {status.Text="检查记录尚未写完；继续检查可复用已保存的目录缓存。";}
    }
}
