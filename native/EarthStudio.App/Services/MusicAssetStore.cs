using System.Security.Cryptography;

namespace EarthStudio.App.Services;

// Immutable local audition media; never overwrites a user source or enters scientific cleanup.
static class MusicAssetStore
{
    public static async Task<object> ImportAsync(string source)
    {
        var extension=Path.GetExtension(source).ToLowerInvariant();
        if(extension is not (".wav" or ".mp3"))throw new ArgumentException("请选择WAV或MP3。");
        var directory=Path.Combine(AppPaths.UserData,"MusicAssets");Directory.CreateDirectory(directory);
        var temp=Path.Combine(directory,Guid.NewGuid().ToString("N")+".tmp");
        try
        {
            using(var input=new FileStream(source,FileMode.Open,FileAccess.Read,FileShare.Read,65536,true))
            {
                if(input.Length<=0||input.Length>100L*1024*1024)throw new ArgumentException("请选择100MB以内音乐文件。");
                using var output=new FileStream(temp,FileMode.CreateNew,FileAccess.Write,FileShare.None,65536,true);
                await input.CopyToAsync(output);await output.FlushAsync();
            }
            string hash;using(var input=File.OpenRead(temp))hash=Convert.ToHexString(await SHA256.HashDataAsync(input)).ToLowerInvariant();
            var file=hash+extension;var target=Path.Combine(directory,file);
            if(File.Exists(target))
            {
                using var existing=File.OpenRead(target);
                if(!CryptographicOperations.FixedTimeEquals(await SHA256.HashDataAsync(existing),Convert.FromHexString(hash)))throw new IOException("已有本机音乐副本校验失败，请检查本机音乐资产目录。");
            }
            else File.Move(temp,target);
            return new {id=hash,name=Path.GetFileName(source),url="/music-assets/"+file};
        }
        finally{if(File.Exists(temp))File.Delete(temp);}
    }
}
