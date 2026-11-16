using System.Text.Json;

namespace EarthStudio.App.Services;

sealed record QueueSnapshot(JsonElement State,bool Active);

static class QueueMonitor
{
    // This is the same exclusive byte0 lock as Python's msvcrt.locking.
    // A saved phase string alone cannot establish whether a worker is alive.
    public static bool IsActive(string directory)
    {
        var file=Path.Combine(directory,"queue.lock");
        if(!File.Exists(file))return false;
        using var stream=new FileStream(file,FileMode.Open,FileAccess.ReadWrite,FileShare.ReadWrite|FileShare.Delete);
        try {stream.Lock(0,1);}
        catch(IOException error) when((error.HResult&0xffff) is 32 or 33){return true;}
        stream.Unlock(0,1);return false;
    }
    public static QueueSnapshot Read(string directory)
    {
        using var document=JsonDocument.Parse(AtomicJsonFile.Read(Path.Combine(directory,"state.json")));
        return new(document.RootElement.Clone(),IsActive(directory));
    }
}
