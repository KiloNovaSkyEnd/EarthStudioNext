using Microsoft.UI.Dispatching;

namespace EarthStudio.App;

sealed partial class MainWindow
{
    private DispatcherQueueTimer? queueTimer;
    private bool queuePausePending;
    private void StartQueueMonitor()
    {
        queueTimer=DispatcherQueue.CreateTimer();queueTimer.Interval=TimeSpan.FromSeconds(2);
        queueTimer.Tick+=(_,_)=>PollQueue();queueTimer.Start();
        Closed+=(_,_)=>queueTimer.Stop();
    }
    private void PollQueue()
    {
        if(queues.QueueDirectory==null)return;
        try {
            var snapshot=Services.QueueMonitor.Read(queues.QueueDirectory);
            if(!snapshot.Active)queuePausePending=false;
            pipeline.Observe(snapshot,queuePausePending);
        }
        catch(Exception error) when(error is IOException or UnauthorizedAccessException or System.Text.Json.JsonException)
        {pipeline.ConnectionUnavailable();}
    }
}
