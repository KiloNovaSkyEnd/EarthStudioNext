using System.Text.Json;

namespace EarthStudio.App.Services;

static class PipelineRecovery
{
    public static bool ShouldRestart(int exitCode,string? failure)=>exitCode!=0&&failure==null;
    public static int DelaySeconds(int attempt)=>Math.Min(300,15*(1<<Math.Min(Math.Max(attempt-1,0),5)));
    public static bool PauseRequested(string directory,DateTime began)=>
        File.Exists(Path.Combine(directory,"pause_requested.json"))&&File.GetLastWriteTimeUtc(Path.Combine(directory,"pause_requested.json"))>=began;

    // Use the Python owner's same byte lock while recording a recovery state.
    // Never overwrite another owner's healthy state between crash and restart.
    public static bool Mark(string directory,object recovery,string phase="recovering-worker")
    {
        using var stream=new FileStream(Path.Combine(directory,"queue.lock"),FileMode.Open,FileAccess.ReadWrite,FileShare.ReadWrite|FileShare.Delete);
        try {stream.Lock(0,1);}
        catch(IOException error) when((error.HResult&0xffff) is 32 or 33){return false;}
        try
        {
            var file=Path.Combine(directory,"state.json");
            using var document=JsonDocument.Parse(AtomicJsonFile.Read(file));
            var state=document.RootElement.EnumerateObject().ToDictionary(p=>p.Name,p=>(object?)p.Value.Clone());
            state["phase"]=phase;state["updated_utc"]=DateTimeOffset.UtcNow;state["recovery"]=recovery;
            AtomicJsonFile.Write(file,JsonSerializer.Serialize(state));
            AtomicJsonFile.Write(Path.Combine(directory,"worker_recovery.json"),JsonSerializer.Serialize(recovery));
            return true;
        }
        finally{stream.Unlock(0,1);}
    }
}
