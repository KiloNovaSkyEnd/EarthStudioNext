using EarthStudio.App.Services;

namespace EarthStudio.App;

sealed partial class MainWindow
{
    private async Task RestoreRecentProjectAsync()
    {
        try {
            var path=RecentProject.Read();
            if(path!=null && File.Exists(path))await OpenProjectPathAsync(path);
        }
        catch(Exception error) when(error is IOException or ArgumentException or System.Text.Json.JsonException)
        {status.Text="上次项目暂时无法恢复，请通过“打开项目”重新选择："+error.Message;}
    }
}
