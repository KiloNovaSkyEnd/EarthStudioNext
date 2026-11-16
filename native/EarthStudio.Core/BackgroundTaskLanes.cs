namespace EarthStudio.Core;

public enum BackgroundLane { Production, Catalog, QueueEdit }

/// <summary>Independent work may overlap; ownership/cancellation stays within its lane.</summary>
public sealed class BackgroundTaskLanes : IDisposable
{
    private readonly object gate=new();
    private readonly Dictionary<BackgroundLane,CancellationTokenSource> work=new();
    public bool IsActive(BackgroundLane lane){lock(gate)return work.ContainsKey(lane);}
    public Lease Begin(BackgroundLane lane)
    {
        lock(gate)
        {
            if(work.ContainsKey(lane))throw new InvalidOperationException($"同类后台操作仍在运行：{lane}");
            var source=new CancellationTokenSource();work.Add(lane,source);return new(this,lane,source);
        }
    }
    public void Cancel(BackgroundLane lane)
    {
        CancellationTokenSource? source;lock(gate)work.TryGetValue(lane,out source);
        source?.Cancel();
    }
    private void End(BackgroundLane lane,CancellationTokenSource source)
    {
        lock(gate)
        {
            if(!work.TryGetValue(lane,out var actual)||!ReferenceEquals(actual,source))return;
            work.Remove(lane);
        }
        source.Dispose();
    }
    public void Dispose()
    {
        CancellationTokenSource[] sources;lock(gate){sources=work.Values.ToArray();work.Clear();}
        foreach(var source in sources){source.Cancel();source.Dispose();}
    }
    public sealed class Lease : IDisposable
    {
        private BackgroundTaskLanes? owner;private readonly BackgroundLane lane;private readonly CancellationTokenSource source;
        internal Lease(BackgroundTaskLanes owner,BackgroundLane lane,CancellationTokenSource source){this.owner=owner;this.lane=lane;this.source=source;}
        public CancellationToken Token=>source.Token;
        public void Dispose()=>Interlocked.Exchange(ref owner,null)?.End(lane,source);
    }
}
