using EarthStudio.Core;

var directory = Path.Combine(Path.GetTempPath(), "EarthStudioChecks_" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(directory);
var project = new EarthProject { Name = "中文项目 with spaces", DataDirectory = directory };
var store = new ProjectStore();
var file = Path.Combine(directory, "test.earthproj");
var count = 0;
void Check(bool value, string label) { if (!value) throw new Exception(label); count++; Console.WriteLine("PASS " + label); }
void Reject(EarthProject value, string label)
{
    try { value.Validate(DateTimeOffset.UtcNow); }
    catch (ArgumentException) { Check(true, label); return; }
    throw new Exception("Accepted invalid project: " + label);
}
try
{
    await LiveCatalogChecks.Run(Check,project);
    BackgroundTaskLaneChecks.Run(Check);
    Check(CatalogPages.Count(1525)==16,"1525 catalog rows have16 reachable pages");
    var allPages=Enumerable.Range(0,16).SelectMany(p=>CatalogPages.Indices(1525,p)).ToArray();
    Check(allPages.Length==1525 && allPages.Distinct().Count()==1525 && allPages.First()==1524 && allPages.Last()==0,"Catalog paging loses no records and repeats none");
    Check(CatalogPages.Indices(0,0).Count()==0 && CatalogPages.Indices(1525,15).Count()==25,"Empty and last partial catalog pages");
    await store.SaveAsync(file, project);
    var restored = await store.LoadAsync(file);
    Check(restored.Name == project.Name && restored.Id == project.Id, "Unicode project round trip");
    Check(!System.Text.Json.JsonSerializer.Serialize(new ProductionOptions()).Contains("NightMode"),"Legacy production JSON omits default night mode");
    foreach(var mode in new[]{"ai-vis","ai-vis-ir"})
    {
        var candidate=project with { Production=project.Production with { NightMode=mode } };
        await store.SaveAsync(file,candidate);
        Check((await store.LoadAsync(file)).Production.NightMode==mode,"Night recipe project round trip "+mode);
        Check(!WorkflowRules.SameCatalog(project,candidate),"Night recipe change requires matching band catalog "+mode);
    }
    await store.SaveAsync(file,project);
    var withInventory=project with { InventoryDirectory=directory };
    await store.SaveAsync(file,withInventory);
    Check((await store.LoadAsync(file)).InventoryDirectory==directory,"Catalog pointer survives project reopen");
    Reject(project with { InventoryDirectory="relative" },"Catalog pointer must be absolute");
    Check(restored.Timeline().Count == 3, "Inclusive UTC timeline");
    var single=project with {CaptureMode="single",EndUtc=project.StartUtc};
    Check(single.Timeline().Count==1,"Single frame has exactly one UTC node");
    await store.SaveAsync(file,single);
    Check((await store.LoadAsync(file)).CaptureMode=="single","Single frame mode survives project reopen");
    Reject(single with {EndUtc=single.StartUtc.AddMinutes(10)},"Single frame rejects hidden range");
    Reject(project with {CaptureMode="unknown"},"Unknown capture mode rejected");
    var supported=single with {SatelliteSelection=new(){Mode="manual",Preset="h9",Satellites=new[]{"himawari9"}}};
    Check(WorkflowRules.ProductionBlocker(supported)==null,"Single frame uses normal supported production route");
    Check(WorkflowRules.ProductionBlocker(supported with {Production=new(){NightLightMetres=500}})==null,"500m independent night can use normal H9 JPEG route");
    Check(WorkflowRules.ProductionBlocker(supported with {Production=new(){Format="png"}})!=null,"Unwired format cannot start production");
    Check(!WorkflowRules.SameCatalog(supported,supported with {CaptureMode="sequence"}),"Switching mode invalidates catalog completion");
    Check(!WorkflowRules.SameProduction(supported,supported with {Production=new(){JpegQuality=100}}),"Changed output invalidates frozen plan readiness");
    Check(WorkflowRules.SameCatalog(supported,supported with {Name="Renamed"}),"Renaming does not invalidate catalog evidence");
    Check(restored.SatelliteSelection.Mode=="auto","Older/default project retains automatic satellite selection");
    try { restored.SatelliteSelection.ValidateSearchScope();throw new Exception("Implicit global search accepted"); }
    catch(ArgumentException) { Check(true,"Older automatic project cannot silently search the world"); }
    new SatelliteSelection { Mode="auto",Preset="global" }.ValidateSearchScope();Check(true,"Explicit global preset can search");
    var selected=project with { SatelliteSelection=new() { Mode="manual",Satellites=new[]{"himawari9","goes19"} } };
    await store.SaveAsync(file,selected);
    Check((await store.LoadAsync(file)).SatelliteSelection.Satellites.SequenceEqual(new[]{"himawari9","goes19"}),"Multiple satellites round trip");
    Reject(project with { SatelliteSelection=new() { Mode="manual" } },"Empty manual satellite selection");
    Reject(project with { SatelliteSelection=new() { Mode="manual",Satellites=new[]{"unknown"} } },"Unknown satellite selection");
    Check((project with { StartUtc=new(2026,10,20,13,0,0,TimeSpan.Zero),EndUtc=new(2026,10,21,1,0,0,TimeSpan.Zero),IntervalMinutes=10 }).Timeline().Count==73,
        "Twelve-hour project includes73 nodes without the obsolete49-node limit");
    Check(restored.Production.Format == "jpeg" && restored.Production.HimawariDiskSize == 11000 && restored.Production.NightLightMetres == 1000, "JPEG-primary production defaults");
    var configured = project with { MaterialsDirectory = directory, Production = new() { Format = "tiff", HimawariDiskSize = 22000, JpegQuality = 100, NightLightMetres = 500, KeepL1 = true, KeepIntermediates = true } };
    await store.SaveAsync(file, configured);
    var options = await store.LoadAsync(file);
    Check(options.MaterialsDirectory == directory && options.Production == configured.Production, "Material and retention settings round trip");
    Reject(project with { Production = new() { JpegQuality = 101 } }, "Invalid JPEG quality");
    Reject(project with { Production = new() { Format = "unknown" } }, "Invalid production format");
    Reject(project with { Production = new() { NightLightMetres = 200 } }, "Invalid nightlight profile");
    Reject(project with { MaterialsDirectory = "relative" }, "Relative material path");
    await store.SaveAsync(file,project with { PipelineDirectory=directory });
    Check((await store.LoadAsync(file)).PipelineDirectory==directory,"Queue directory survives project restart");
    Reject(project with { PipelineDirectory="relative" },"Relative queue path");

    foreach (var offset in new[] { -6, 14 })
    {
        var zone = TimeZoneInfo.CreateCustomTimeZone($"Test{offset}", TimeSpan.FromHours(offset), "Test", "Test");
        var utc = new DateTimeOffset(2020, 10, 29, 0, 5, 0, TimeSpan.Zero);
        var pickerValue = UtcCalendar.ForPicker(utc, zone).ToUniversalTime();
        Check(UtcCalendar.FromPicker(pickerValue, utc.TimeOfDay, zone) == utc, $"UTC midnight calendar round trip {offset:+0;-0}");
    }
    await store.SaveAsync(file, project with { Name = "Second save" });
    Check((await store.LoadAsync(file)).Name == "Second save", "Atomic replacement");
    Reject(project with { EndUtc = project.StartUtc }, "Empty interval");
    Reject(project with { EndUtc = DateTimeOffset.UtcNow.AddDays(1) }, "Future interval");
    Reject(project with { StartUtc = project.StartUtc.ToOffset(TimeSpan.FromHours(8)) }, "Non-UTC timestamps");
    Reject(project with { DataDirectory = "relative/path" }, "Relative archive path");
    Reject(project with { SchemaVersion = 99 }, "Unknown schema");
    Reject(project with { IntervalMinutes = 0 }, "Invalid interval");
    var before = await File.ReadAllTextAsync(file);
    try { await store.SaveAsync(file, project with { Name = "" }); throw new Exception("Invalid save succeeded"); }
    catch (ArgumentException) { Check(await File.ReadAllTextAsync(file) == before, "Invalid save preserves project"); }
    await File.WriteAllTextAsync(file, "{broken");
    try { await store.LoadAsync(file); throw new Exception("Corrupt file accepted"); }
    catch (System.Text.Json.JsonException) { Check(true, "Corrupt project rejected"); }
    Console.WriteLine($"{count} checks passed");
}
finally
{
    foreach (var entry in Directory.EnumerateFiles(directory)) File.Delete(entry);
    Directory.Delete(directory);
}
