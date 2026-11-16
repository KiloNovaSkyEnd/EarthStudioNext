using System.Text;

namespace EarthStudio.App.Services;

static class AtomicJsonFile
{
    public static string Read(string path)
    {
        using var file=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete);
        using var reader=new StreamReader(file,Encoding.UTF8);return reader.ReadToEnd();
    }
    public static void Write(string path,string content)
    {
        var temporary=path+"."+Guid.NewGuid().ToString("N")+".part";
        using(var file=new FileStream(temporary,FileMode.CreateNew,FileAccess.Write,FileShare.None))
        {
            var bytes=Encoding.UTF8.GetBytes(content);file.Write(bytes);file.Flush(true);
        }
        var until=DateTime.UtcNow.AddSeconds(5);
        while(true)
        {
            try{File.Move(temporary,path,true);return;}
            catch(Exception error) when ((error is IOException or UnauthorizedAccessException) &&
                (error.HResult&0xffff) is 5 or 32 or 33 && DateTime.UtcNow<until)
            {Thread.Sleep(50);}
        }
    }
}
