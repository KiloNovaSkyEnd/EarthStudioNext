namespace EarthStudio.Core;

public readonly record struct QueueControlState(bool Busy,bool CanStart,bool CanPause,bool Stopped)
{
    public static QueueControlState Evaluate(bool localBusy,bool locked,bool known,bool pausePending,string phase)
    {
        var busy=localBusy||locked||!known;
        return new(busy,known&&!busy,known&&(localBusy||locked)&&!pausePending,
            known&&!localBusy&&!locked&&IsRunningPhase(phase));
    }
    public static bool IsRunningPhase(string phase)=>phase is "parallel-running" or "parallel-progress" or
        "checking-completed" or "recovering-worker" or "waiting-resources" or "acquiring" or "producing" or "verifying" or "verifying-assets" or "cleaning" or "step-complete";
}
