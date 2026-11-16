namespace EarthStudio.Core;

/// <summary>Serial latest-request execution. Superseded attempts cannot overlap their replacement.</summary>
public sealed class LiveCatalogRequest
{
    private (EarthProject Project, bool Refresh)? pending;
    private CancellationTokenSource? attempt;
    public bool IsRunning { get; private set; }
    public EarthProject? Requested { get; private set; }

    public bool Request(EarthProject value, bool refresh = false)
    {
        if (!refresh && Requested is {} old && WorkflowRules.SameCatalog(old,value) &&
            string.Equals(old.DataDirectory,value.DataDirectory,StringComparison.OrdinalIgnoreCase)) return false;
        Requested=value;pending=(value,refresh);attempt?.Cancel();return true;
    }

    public async Task RunAsync(EarthProject initial, bool refresh,
        Func<EarthProject,bool,CancellationToken,Task> execute, CancellationToken cancellation)
    {
        if(IsRunning)throw new InvalidOperationException("Catalog session already running");
        IsRunning=true;
        try
        {
            Request(initial,refresh);
            while(pending is {} next)
            {
                cancellation.ThrowIfCancellationRequested();pending=null;
                attempt=CancellationTokenSource.CreateLinkedTokenSource(cancellation);
                try {await execute(next.Project,next.Refresh,attempt.Token);}
                catch(OperationCanceledException) when(!cancellation.IsCancellationRequested && pending!=null) { }
                finally {attempt.Dispose();attempt=null;}
            }
        }
        finally {IsRunning=false;Requested=null;pending=null;}
    }
}
