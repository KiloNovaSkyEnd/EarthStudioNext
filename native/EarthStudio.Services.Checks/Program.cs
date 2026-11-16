using System.Net.Sockets;
using System.Text.Json;
using EarthStudio.App;
using EarthStudio.App.Services;

var root = AppPaths.FindEngineRoot() ?? throw new Exception("Run from Next workspace");
var materials = Path.Combine(root, "data", "cesium_h9_motion_20261020");
var report = new List<string>();
void Check(bool value, string label) { if (!value) throw new Exception(label); report.Add(label); Console.WriteLine("PASS " + label); }
var store = new WorkspaceDocumentStore();
using var first = JsonDocument.Parse("{\"schema\":\"earthstudio.timeline.v1\",\"tracks\":[{\"name\":\"中文试验A\"}]}");
using var second = JsonDocument.Parse("{\"schema\":\"earthstudio.timeline.v1\",\"tracks\":[{\"name\":\"中文试验B\"}]}");
var a = Guid.NewGuid(); var b = Guid.NewGuid();
await store.SaveDraftAsync(materials, a, first.RootElement);
await store.SaveDraftAsync(materials, b, second.RootElement);
var reopened = new WorkspaceDocumentStore();
Check((await reopened.ReadDraftAsync(materials, a))!.Contains("试验A"), "Draft restores without renderer origin/localStorage");
Check((await reopened.ReadDraftAsync(materials, b))!.Contains("试验B"), "Same-material projects keep independent drafts");
await store.SaveDraftAsync(materials, a, second.RootElement);
Check((await reopened.ReadDraftAsync(materials, a))!.Contains("试验B"), "Atomic draft update");
using var bad = JsonDocument.Parse("{\"schema\":\"unknown\"}");
try { await store.SaveAsync("camera-export", bad.RootElement); throw new Exception("Bad schema accepted"); }
catch (ArgumentException) { Check(true, "Bad export schema rejected"); }
var host = new LocalStudioHost();
var uri = await host.StartAsync(materials);
Check(uri.Host == "127.0.0.1" && uri.Port > 0, "Owned dynamic loopback port");
using var http = new HttpClient();
using var index = JsonDocument.Parse(await http.GetStringAsync(new Uri(uri, "data/manifest.json")));
Check(index.RootElement.GetProperty("frames").GetArrayLength() == 73, "Actual73-node material index served");
var html = await http.GetStringAsync(new Uri(uri, "index.html"));
Check(html.Contains("deleteKey"), "Current local renderer assets served");
host.Dispose();
await Task.Delay(300);
using var socket = new TcpClient();
bool stopped;
try { await socket.ConnectAsync("127.0.0.1", uri.Port); stopped = false; }
catch (SocketException) { stopped = true; }
Check(stopped, "Dispose closes only owned server");
var producer=new ProductionJobsClient();
var h9Selection=new EarthStudio.Core.SatelliteSelection { Mode="manual",Satellites=new[]{"himawari9"} };
foreach (var settings in new[] {
    new EarthStudio.Core.ProductionOptions { Format="png" },
    new EarthStudio.Core.ProductionOptions { HimawariDiskSize=22000 },
    new EarthStudio.Core.ProductionOptions { NightLightMetres=500 } }) {
    bool rejected=false;
    try { await producer.RunAsync(new EarthStudio.Core.EarthProject { Production=settings,SatelliteSelection=h9Selection },"2026-10-20T13:00:00Z",_=>{},CancellationToken.None); }
    catch (ArgumentException) { rejected=true; }
    Check(rejected,"Unsupported new production profile rejected before processing: "+settings);
}
bool badUtc=false;
try { await producer.RunAsync(new EarthStudio.Core.EarthProject { SatelliteSelection=h9Selection },"2026-10-20T13:01:00Z",_=>{},CancellationToken.None); }
catch (ArgumentException) { badUtc=true; }
Check(badUtc,"Partial scan UTC rejected before processing");
bool wrongSatellite=false;
try { await producer.RunAsync(new EarthStudio.Core.EarthProject { SatelliteSelection=new() { Mode="manual",Satellites=new[]{"goes19"} } },"2026-10-20T13:00:00Z",_=>{},CancellationToken.None); }
catch (ArgumentException) { wrongSatellite=true; }
Check(wrongSatellite,"H9 production refuses an unrelated selected satellite");
var output = Path.Combine(root, "reports", "native_desktop_m2"); Directory.CreateDirectory(output);
await File.WriteAllTextAsync(Path.Combine(output, "service_checks.json"), JsonSerializer.Serialize(new { passed = report.Count, checks = report }, new JsonSerializerOptions { WriteIndented = true }));
