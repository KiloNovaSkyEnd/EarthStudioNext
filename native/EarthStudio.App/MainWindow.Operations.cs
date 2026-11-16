using EarthStudio.Core;

namespace EarthStudio.App;

sealed partial class MainWindow
{
    private void RefreshCancelButton()
    {
        cancel.IsEnabled=running!=null || background.IsActive(BackgroundLane.Catalog) || background.IsActive(BackgroundLane.QueueEdit) || background.IsActive(BackgroundLane.Production);
        cancel.Content=background.IsActive(BackgroundLane.Catalog)?"取消当前数据检查":
            background.IsActive(BackgroundLane.QueueEdit)?"取消当前队列变更":
            background.IsActive(BackgroundLane.Production)?"安全暂停当前制作":"取消后台任务";
    }
    private void CancelSelectedOperation()
    {
        // Searching must never cancel a simultaneously running production owner.
        if(background.IsActive(BackgroundLane.Catalog))background.Cancel(BackgroundLane.Catalog);
        else if(background.IsActive(BackgroundLane.QueueEdit))background.Cancel(BackgroundLane.QueueEdit);
        else if(running!=null)running.Cancel();
        else if(background.IsActive(BackgroundLane.Production))
        {
            if(queues.RequestSafePause()){queuePausePending=true;PollQueue();}
            else background.Cancel(BackgroundLane.Production);
        }
    }
}
