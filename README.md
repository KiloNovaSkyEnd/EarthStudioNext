# Earth Studio Next

面向 Windows x64 的卫星气象素材制作和分镜编辑工具。这是 M18 桌面版的首次公开预览。界面支持按 UTC 查询观测，制作 Himawari-9 11K 圆盘 JPEG 序列，编辑相机关键帧，并导出可继续编辑的 Blender 工程。

## 下载和启动

1. 打开 [GitHub Releases](https://github.com/KiloNovaSkyEnd/EarthStudioNext/releases/tag/v0.1.0-m18)，下载 `EarthStudioNext-Windows-x64.zip`，解压到可写文件夹，例如 `C:\EarthStudioNext`。
2. 要制作卫星天气素材，把两个 `EarthStudioNext-NightReference-*.zip` 都解压到同一个文件夹。接受目录合并。两包共约 2.4 GB，解压后会补齐应用内 `resources\references\blackmarble_2016_500m` 下的八个 NASA 夜景瓦片。
3. 要导出或校验 Blender 项目，把 `EarthStudioNext-Blender-win-x64.zip` 解压到同一文件夹。应用也能使用标准路径安装的 Blender，或通过 `EARTHSTUDIO_BLENDER` 指向已有的 `blender.exe`。
4. 要启用 AI-VIS 和 AI-VIS+IR，把 `EarthStudioNext-AI-VIS-win-x64.zip` 解压到同一文件夹，并使用支持 CUDA 的 NVIDIA 显卡和兼容驱动。默认 GeoColor 不依赖此附加包。
5. 双击 `EarthStudio.App.exe`。桌面程序内置 .NET、WinUI、科学 Python 以及 Cesium。编辑预览使用 Windows 的 [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。
6. 在软件中另选可写的数据目录，然后按顺序创建项目、选择 UTC 范围、查询与预检、生成制作队列。所选时间的原始卫星观测会按需联网下载，单次制作可能需要大量磁盘空间。

GitHub 自动生成的 **Source code** 压缩包用于开发。从 **Assets** 下载 Windows 便携包。发布页的 `SHA256SUMS.txt` 可与 `Get-FileHash -Algorithm SHA256 路径` 的输出比对。

## 源码构建

使用 Windows x64、.NET 8 SDK 和 Python 3.12。在仓库根目录运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-science-lock.txt -r requirements-visual.txt
@{python_executable=(Resolve-Path .\.venv\Scripts\python.exe).Path; development_only=$true} |
    ConvertTo-Json | Set-Content -Encoding utf8NoBOM development_runtime.json
dotnet publish native/EarthStudio.App/EarthStudio.App.csproj -c Release -r win-x64 --self-contained true -o app
.\app\EarthStudio.App.exe
```

以上命令使用 PowerShell 7。要以源码运行进行完整制作，将发布包中的 `data/raw/reference`、`resources` 与 `Runtime` 合并到源码根目录。生产验证可以通过 PowerShell 执行 `dotnet run --project native/EarthStudio.Core.Checks`。

## 当前范围

目录查询与素材制作是不同阶段。当前桌面制作队列支持 Himawari-9 单星 11K JPEG。部分观测可能缺失，单星圆盘覆盖随观测几何变化。AI-VIS 用红外数据推算夜间可见光外观。Blender 渲染队列界面可生成任务清单，自动执行仍在开发。不同硬件上的全流程产出和长时间 4K 序列尚待验证。

第三方资源来源和许可见 [THIRD-PARTY.md](THIRD-PARTY.md)。
