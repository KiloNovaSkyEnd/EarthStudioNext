using System.Diagnostics;
using System.Text.Json;
using System.Threading;
var python = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "AI", "python.exe"));
if (!File.Exists(python))
{
    Console.Error.WriteLine("Install the Earth Studio Next AI-VIS runtime before using this mode.");
    return 2;
}
using var slot=new Mutex(false,"Local\\EarthStudio_AI_GPU_Inference_v1");
var acquired=false;
try
{
    Console.WriteLine($"AI_GPU_SLOT_WAIT {DateTimeOffset.UtcNow:O}");
    try{slot.WaitOne();acquired=true;}catch(AbandonedMutexException){acquired=true;}
    Console.WriteLine($"AI_GPU_SLOT_ACQUIRED {DateTimeOffset.UtcNow:O}");
    var start=new ProcessStartInfo(python){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=Environment.CurrentDirectory,RedirectStandardOutput=true,RedirectStandardError=true};
    foreach(var arg in args)start.ArgumentList.Add(arg);
    using var child=Process.Start(start)??throw new IOException("Cannot start qualified GPU Python.");
    var pumps=Task.WhenAll(child.StandardOutput.BaseStream.CopyToAsync(Console.OpenStandardOutput()),child.StandardError.BaseStream.CopyToAsync(Console.OpenStandardError()));
    child.WaitForExit();pumps.GetAwaiter().GetResult();return child.ExitCode;
}
finally{if(acquired)slot.ReleaseMutex();}
