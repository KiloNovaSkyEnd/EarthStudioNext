using Windows.Storage.Pickers;

namespace EarthStudio.App.Services;

sealed class PickerService(nint windowHandle)
{
    public async Task<string?> OpenMusicAsync()
    {
        var picker=new FileOpenPicker();picker.FileTypeFilter.Add(".wav");picker.FileTypeFilter.Add(".mp3");
        WinRT.Interop.InitializeWithWindow.Initialize(picker,windowHandle);
        return (await picker.PickSingleFileAsync())?.Path;
    }
    public async Task<string?> OpenBlenderAsync()
    {
        var picker=new FileOpenPicker();picker.FileTypeFilter.Add(".blend");
        WinRT.Interop.InitializeWithWindow.Initialize(picker,windowHandle);
        return (await picker.PickSingleFileAsync())?.Path;
    }
    public async Task<string?> OpenInventoryAsync()
    {
        var picker=new FileOpenPicker();picker.FileTypeFilter.Add(".json");
        WinRT.Interop.InitializeWithWindow.Initialize(picker,windowHandle);
        return (await picker.PickSingleFileAsync())?.Path;
    }
    public async Task<string?> OpenProjectAsync()
    {
        var picker = new FileOpenPicker(); picker.FileTypeFilter.Add(".earthproj");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, windowHandle);
        return (await picker.PickSingleFileAsync())?.Path;
    }
    public async Task<string?> SaveProjectAsync(string name)
    {
        var picker = new FileSavePicker { SuggestedFileName = string.Concat(name.Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c)) };
        picker.FileTypeChoices.Add("Earth Studio 项目", new List<string> { ".earthproj" });
        WinRT.Interop.InitializeWithWindow.Initialize(picker, windowHandle);
        return (await picker.PickSaveFileAsync())?.Path;
    }
    public async Task<string?> FolderAsync()
    {
        var picker = new FolderPicker(); picker.FileTypeFilter.Add("*");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, windowHandle);
        return (await picker.PickSingleFolderAsync())?.Path;
    }
}
