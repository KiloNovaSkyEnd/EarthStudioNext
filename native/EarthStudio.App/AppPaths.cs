namespace EarthStudio.App;

static class AppPaths
{
    public static string UserData => Path.Combine(
        Environment.GetEnvironmentVariable("EARTHSTUDIO_LOCALAPPDATA")
        ?? Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Deepsky", "EarthStudioNext");

    public static string BlenderExecutable
    {
        get
        {
            var configured = Environment.GetEnvironmentVariable("EARTHSTUDIO_BLENDER");
            if (!string.IsNullOrWhiteSpace(configured)) return configured;
            var root = FindEngineRoot() ?? AppContext.BaseDirectory;
            var bundled = Path.Combine(root, "Runtime", "Blender", "blender.exe");
            if (File.Exists(bundled)) return bundled;
            var installed = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Blender Foundation");
            if (Directory.Exists(installed))
            {
                foreach (var directory in Directory.EnumerateDirectories(installed).OrderByDescending(path => path))
                {
                    var executable = Path.Combine(directory, "blender.exe");
                    if (File.Exists(executable)) return executable;
                }
            }
            return "blender.exe";
        }
    }
    public static string DevelopmentPython
    {
        get
        {
            var root = FindEngineRoot() ?? AppContext.BaseDirectory;
            var bundled = Path.Combine(root, "Runtime", "Python", "python.exe");
            if (File.Exists(bundled)) return bundled;
            var file = Path.Combine(root, "development_runtime.json");
            if(!File.Exists(file)) return "";
            using var config=System.Text.Json.JsonDocument.Parse(File.ReadAllText(file));
            return config.RootElement.GetProperty("python_executable").GetString() ?? "";
        }
    }
    public static void RequireWritable(string path)
    {
        var target=Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar);
        var root=FindEngineRoot() ?? AppContext.BaseDirectory;
        bool Within(string candidate,string parent) => candidate.Equals(parent,StringComparison.OrdinalIgnoreCase) || candidate.StartsWith(parent+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase);
        var config=Path.Combine(root,"protected_roots.json");
        if(File.Exists(config))
        {
            using var document=System.Text.Json.JsonDocument.Parse(File.ReadAllText(config));
            foreach(var item in document.RootElement.GetProperty("read_only_roots").EnumerateArray())
                if(Within(target,Path.GetFullPath(item.GetString()!).TrimEnd(Path.DirectorySeparatorChar))) throw new InvalidOperationException("旧版软件和素材只读；请使用新版独立目录。");
        }
        var registry=Path.Combine(UserData,"storage_locations.json");
        var locations=File.Exists(registry)?System.Text.Json.JsonSerializer.Deserialize<string[]>(File.ReadAllText(registry))??Array.Empty<string>():Array.Empty<string>();
        if(!Within(target,root) && !Within(target,UserData) && !locations.Any(p=>Within(target,Path.GetFullPath(p).TrimEnd(Path.DirectorySeparatorChar)))) throw new InvalidOperationException("请通过“选择数据目录”登记新的制作位置；外部目录记录可导入复用。");
    }
    public static void RegisterDataDirectory(string path)
    {
        var full=Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar);
        if(full.Length<4 || full.Equals(Path.GetPathRoot(path)?.TrimEnd(Path.DirectorySeparatorChar),StringComparison.OrdinalIgnoreCase))throw new ArgumentException("请选择磁盘下的独立项目文件夹，不要选磁盘根目录。");
        var file=Path.Combine(UserData,"storage_locations.json");Directory.CreateDirectory(UserData);
        var roots=File.Exists(file)?System.Text.Json.JsonSerializer.Deserialize<List<string>>(File.ReadAllText(file))??new():new List<string>();
        // Register only after applying the protected-root check independently.
        var protectedFile=Path.Combine(FindEngineRoot()??AppContext.BaseDirectory,"protected_roots.json");
        if(File.Exists(protectedFile))
        {
            using var doc=System.Text.Json.JsonDocument.Parse(File.ReadAllText(protectedFile));
            foreach(var r in doc.RootElement.GetProperty("read_only_roots").EnumerateArray())
            {
                var protectedPath=Path.GetFullPath(r.GetString()!).TrimEnd(Path.DirectorySeparatorChar);
                if(full.Equals(protectedPath,StringComparison.OrdinalIgnoreCase)||full.StartsWith(protectedPath+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)||protectedPath.StartsWith(full+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new ArgumentException("不能将旧版受保护资料或其父目录作为新项目存储位置。");
            }
        }
        if(!roots.Contains(full,StringComparer.OrdinalIgnoreCase))roots.Add(full);
        var temp=file+"."+Guid.NewGuid().ToString("N")+".tmp";File.WriteAllText(temp,System.Text.Json.JsonSerializer.Serialize(roots));File.Move(temp,file,true);
    }
    public static string ScientificEngine => Path.Combine(AppContext.BaseDirectory,"Engine","EarthScience.Engine.exe");
    public static string FindAuxiliaryReferenceRoot()
    {
        for(var directory=new DirectoryInfo(FindEngineRoot()??AppContext.BaseDirectory);directory!=null;directory=directory.Parent)
            foreach(var reference in new[]{Path.Combine(directory.FullName,"data/raw/reference"),Path.Combine(directory.FullName,"GlobalSatelliteEarthStudio/data/raw/reference")})
                if(File.Exists(Path.Combine(reference,"satpy_geocolor_v060/composites/gshhs_land_water_mask_3km_i.tif")))return Path.GetFullPath(reference);
        throw new IOException("未找到地表辅助参考，请恢复软件共享参考目录；尚未开始下载，已有输入保留。");
    }
    public static string? FindEngineRoot()
    {
        foreach (var origin in new[] { AppContext.BaseDirectory, Environment.CurrentDirectory })
        {
            for (var directory = new DirectoryInfo(origin); directory != null; directory = directory.Parent)
                if (File.Exists(Path.Combine(directory.FullName, "ges", "native_bridge.py"))) return directory.FullName;
        }
        return null;
    }
}
