using EarthStudio.Core;

static class LiveCatalogChecks
{
    public static async Task Run(Action<bool,string> check,EarthProject project)
    {
        var latest=new LiveCatalogRequest();var seen=new List<EarthProject>();
        var completed=new List<EarthProject>();var active=0;var maximum=0;
        var allowReplacement=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var original=project with {StartUtc=new(2026,10,20,0,0,0,TimeSpan.Zero),EndUtc=new(2026,10,21,0,0,0,TimeSpan.Zero)};
        var wider=original with {EndUtc=original.EndUtc.AddDays(1)};
        var smaller=original with {StartUtc=original.StartUtc.AddHours(6),EndUtc=original.StartUtc.AddHours(12)};
        async Task Execute(EarthProject value,bool refresh,CancellationToken token)
        {
            active++;maximum=Math.Max(maximum,active);seen.Add(value);
            try
            {
                if(seen.Count==1)
                {
                    try {await Task.Delay(Timeout.Infinite,token);}
                    catch(OperationCanceledException){await allowReplacement.Task;throw;}
                }
                token.ThrowIfCancellationRequested();completed.Add(value);
            }
            finally {active--;}
        }
        var run=latest.RunAsync(original,false,Execute,CancellationToken.None);
        check(!latest.Request(original),"Same catalog range does not restart active query");
        latest.Request(wider);latest.Request(smaller);
        allowReplacement.SetResult();
        await run;
        check(seen.Count==2 && seen[1]==smaller,"Rapid expand then shrink executes only latest date range");
        check(maximum==1 && completed.SequenceEqual(new[]{smaller}),"Superseded catalog cannot overlap or complete over latest range");
        check(!latest.IsRunning && latest.Requested==null,"Latest range session releases its state");
        using var cancel=new CancellationTokenSource();var started=new TaskCompletionSource();
        var releaseCancel=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var stopped=latest.RunAsync(original,false,async (_,_,token)=>
        {
            started.SetResult();
            try {await Task.Delay(Timeout.Infinite,token);}
            catch(OperationCanceledException){await releaseCancel.Task;throw;}
        },cancel.Token);
        await started.Task;latest.Request(wider);cancel.Cancel();
        releaseCancel.SetResult();
        try {await stopped;throw new Exception("Cancellation ignored");}
        catch(OperationCanceledException) {check(!latest.IsRunning,"Manual cancel stops even a pending replacement range");}
        var refreshed=false;
        await latest.RunAsync(smaller,true,(_,refresh,_)=>{refreshed=refresh;return Task.CompletedTask;},CancellationToken.None);
        check(refreshed,"Explicit refresh is separate from automatic cache-reusing retarget");
    }
}
