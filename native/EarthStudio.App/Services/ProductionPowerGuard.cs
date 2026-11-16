using System.Runtime.InteropServices;

namespace EarthStudio.App.Services;

sealed class ProductionPowerGuard : IDisposable
{
    private readonly ManualResetEventSlim stop=new(false),ready=new(false);
    private readonly Thread? owner;
    public bool Active {get;private set;}
    [DllImport("kernel32.dll")]private static extern uint SetThreadExecutionState(uint flags);
    public ProductionPowerGuard(Func<uint,uint>? setter=null)
    {
        if(setter==null&&!OperatingSystem.IsWindows()){ready.Set();return;}
        setter ??= SetThreadExecutionState;
        owner=new Thread(()=>
        {
            var previous=setter(0x80000001);Active=previous!=0;ready.Set();
            try{stop.Wait();}finally{if(previous!=0)setter(previous);}
        }){IsBackground=true,Name="EarthStudio production power guard"};
        owner.Start();ready.Wait();
    }
    public void Dispose(){stop.Set();owner?.Join();stop.Dispose();ready.Dispose();}
}
