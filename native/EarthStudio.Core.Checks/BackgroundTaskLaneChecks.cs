using EarthStudio.Core;

static class BackgroundTaskLaneChecks
{
    public static void Run(Action<bool,string> check)
    {
        using var lanes=new BackgroundTaskLanes();
        using var production=lanes.Begin(BackgroundLane.Production);
        var catalog=lanes.Begin(BackgroundLane.Catalog);
        using var edit=lanes.Begin(BackgroundLane.QueueEdit);
        check(lanes.IsActive(BackgroundLane.Production)&&lanes.IsActive(BackgroundLane.Catalog)&&lanes.IsActive(BackgroundLane.QueueEdit),"Production, catalog search and queue edits can overlap");
        try {using var duplicate=lanes.Begin(BackgroundLane.Production);throw new Exception("Duplicate production accepted");}
        catch(InvalidOperationException){check(true,"A second production owner is rejected");}
        lanes.Cancel(BackgroundLane.Catalog);
        check(catalog.Token.IsCancellationRequested&&!production.Token.IsCancellationRequested&&!edit.Token.IsCancellationRequested,"Cancel search preserves production and queue edit tokens");
        catalog.Dispose();using var next=lanes.Begin(BackgroundLane.Catalog);catalog.Dispose();
        check(lanes.IsActive(BackgroundLane.Catalog)&&!next.Token.IsCancellationRequested,"An old completed search cannot release a new search owner");
        edit.Dispose();production.Dispose();
        check(!lanes.IsActive(BackgroundLane.Production)&&lanes.IsActive(BackgroundLane.Catalog),"Finishing production does not block or cancel current catalog search");
    }
}
