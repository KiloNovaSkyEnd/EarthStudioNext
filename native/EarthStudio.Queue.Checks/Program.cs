using System.Diagnostics;
using System.Text.Json;
using EarthStudio.App.Services;
using EarthStudio.Core;

var count=0;
void Check(bool condition,string label){if(!condition)throw new Exception(label);Console.WriteLine("PASS "+label);count++;}
var root=Directory.GetCurrentDirectory();
using var runtime=JsonDocument.Parse(File.ReadAllText(Path.Combine(root,"development_runtime.json")));
var python=runtime.RootElement.GetProperty("python_executable").GetString()!;
var folder=Path.Combine(root,"reports","queue_connection_checks",Guid.NewGuid().ToString("N"));Directory.CreateDirectory(folder);
var state=Path.Combine(folder,"state.json");AtomicJsonFile.Write(state,"{\"phase\":\"parallel-running\",\"completed\":[\"fixture\"]}");
Check(!QueueMonitor.Read(folder).Active,"Saved running phase alone is not an active worker");
var control=QueueControlState.Evaluate(false,false,true,false,"parallel-running");
Check(control.Stopped&&control.CanStart&&!control.CanPause,"Stale running state offers Continue");
control=QueueControlState.Evaluate(false,true,true,false,"parallel-running");
Check(!control.CanStart&&control.CanPause,"External running task can pause and cannot duplicate start");
control=QueueControlState.Evaluate(false,true,true,true,"parallel-running");
Check(!control.CanStart&&!control.CanPause&&control.Busy,"Pending safe pause stays busy until lock release");
control=QueueControlState.Evaluate(false,false,false,false,"parallel-running");
Check(!control.CanStart&&!control.CanPause,"Unknown activity fails closed");
var start=new ProcessStartInfo(python){WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardInput=true,RedirectStandardOutput=true};
foreach(var arg in new[]{"-u","-c","from pathlib import Path;from ges_next.pipeline.locking import exclusive;import sys;\nwith exclusive(Path(sys.argv[1])):\n print('READY',flush=True);sys.stdin.read()",Path.Combine(folder,"queue.lock")})start.ArgumentList.Add(arg);
using(var owner=Process.Start(start)!)
{
    Check(await owner.StandardOutput.ReadLineAsync()=="READY","Python owner acquired actual kernel lock");
    Check(QueueMonitor.Read(folder).Active,"C# detects Python msvcrt lock across processes");
    Check(!PipelineRecovery.Mark(folder,new {attempt=1}),"Recovery cannot overwrite a healthy queue owner");
    Check(QueueMonitor.Read(folder).State.GetProperty("completed").GetArrayLength()==1,"Monitoring retains completed count");
    owner.Kill(true);await owner.WaitForExitAsync();
}
Check(!QueueMonitor.Read(folder).Active,"Owner crash releases lock without stale PID cleanup");
control=QueueControlState.Evaluate(false,false,true,false,"paused-user");
Check(control.CanStart&&!control.CanPause,"Paused task allows Continue");
AtomicJsonFile.Write(state,"{broken");
try{QueueMonitor.Read(folder);throw new Exception("Corrupt state accepted");}catch(JsonException){Check(true,"Corrupt state is not mistaken for idle");}
Console.WriteLine($"{count} checks passed");
Check(PipelineRecovery.ShouldRestart(-1073741819,null),"Unexpected worker crash is recoverable");
Check(!PipelineRecovery.ShouldRestart(1,"quality mismatch"),"Explicit quality/data failures never auto restart");
Check(PipelineRecovery.DelaySeconds(100)==300,"Worker restart interval is capped");
using(var doc=JsonDocument.Parse("{\"phase\":\"parallel-running\",\"waiting_reason\":\"space\",\"active\":[{\"utc\":\"fixture\",\"phase\":\"waiting-network\",\"retry\":{\"attempt\":20,\"retry_seconds\":60}}]}"))
{
    var text=EarthStudio.App.UI.PipelineStatusText.Describe(doc.RootElement);
    Check(text.Contains("自动重连")&&text.Contains("磁盘余量不足"),"UI explains automatic network and resource recovery");
}
AtomicJsonFile.Write(state,"{\"phase\":\"parallel-running\",\"completed\":[\"fixture\"]}");
var recoveryScript=Path.Combine(folder,"crash_fixture.py");
await File.WriteAllTextAsync(recoveryScript,"import sys,os,json\nfrom pathlib import Path\np=Path(sys.argv[1]); counter=p/'attempts'; n=int(counter.read_text())+1 if counter.exists() else 1;counter.write_text(str(n))\nif n==1:os._exit(7)\ns=p/'state.json';v=json.loads(s.read_text());v['phase']='complete';s.write_text(json.dumps(v));print(json.dumps(v),flush=True)\n");
ProcessStartInfo Fixture(string script)
{
    var info=new ProcessStartInfo(python){WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};
    foreach(var arg in new[]{"-u",script,folder})info.ArgumentList.Add(arg);return info;
}
var reports=new List<JsonElement>();
await PipelineWorkerSupervisor.RunAsync(Fixture(recoveryScript),"run",folder,v=>reports.Add(v),CancellationToken.None,(_,_)=>Task.CompletedTask);
Check(File.ReadAllText(Path.Combine(folder,"attempts"))=="2","Real child abrupt exit automatically restarts and completes");
Check(reports.Any(v=>v.GetProperty("phase").GetString()=="recovering-worker"),"Crash restart emits visible recovery status");
Check(QueueMonitor.Read(folder).State.GetProperty("completed").GetArrayLength()==1,"Crash recovery preserves completed results");
var failScript=Path.Combine(folder,"fatal_fixture.py");
await File.WriteAllTextAsync(failScript,"import json,sys\nprint(json.dumps(dict(phase='error',error='quality mismatch')),flush=True);sys.exit(1)\n");
try{await PipelineWorkerSupervisor.RunAsync(Fixture(failScript),"run",folder,_=>{},CancellationToken.None,(_,_)=>Task.CompletedTask);throw new Exception("Explicit failure restarted");}
catch(IOException){Check(true,"Real child explicit quality failure stops and is not retried");}
var cancelScript=Path.Combine(folder,"cancel_fixture.py");await File.WriteAllTextAsync(cancelScript,"import os;os._exit(7)\n");
using(var cancellation=new CancellationTokenSource())
{
    try
    {
        await PipelineWorkerSupervisor.RunAsync(Fixture(cancelScript),"run",folder,_=>{},cancellation.Token,(_,token)=>{cancellation.Cancel();return Task.FromCanceled(token);});
        throw new Exception("Cancellation ignored");
    }
    catch(OperationCanceledException){Check(true,"User cancellation interrupts crash restart wait");}
}
await PipelineWorkerSupervisor.RunAsync(Fixture(cancelScript),"run",folder,_=>{},CancellationToken.None,(_,_)=>
{
    AtomicJsonFile.Write(Path.Combine(folder,"pause_requested.json"),"{}");return Task.CompletedTask;
});
Check(QueueMonitor.Read(folder).State.GetProperty("phase").GetString()=="paused-user","Safe pause during recovery prevents another restart");
Console.WriteLine($"{count} total checks passed");
var powerCalls=new List<(uint Flags,int Thread)>();
using(var guard=new ProductionPowerGuard(flags=>{powerCalls.Add((flags,Environment.CurrentManagedThreadId));return 0x80000000;}))
{Check(guard.Active,"Power guard holds across worker restart waits");}
Check(powerCalls.Count==2&&powerCalls[0].Flags==0x80000001&&powerCalls[1].Flags==0x80000000&&powerCalls[0].Thread==powerCalls[1].Thread,"Power request released on the owning thread");
using(var liveGuard=new ProductionPowerGuard()){Check(liveGuard.Active,"Actual Windows system awake request succeeds");}
Console.WriteLine($"{count} final checks passed");
