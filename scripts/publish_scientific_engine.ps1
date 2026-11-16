param([Parameter(Mandatory=$true)][string]$OutputDirectory,
      [Parameter(Mandatory=$true)][string]$BuildDirectory)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$python=Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath (Join-Path $OutputDirectory 'EarthScience.Engine')) {
    throw 'Choose a new output directory; completed engines are preserved.'
}
& $python -m PyInstaller --noconfirm --onedir --name EarthScience.Engine --paths $projectRoot `
    --distpath $OutputDirectory --workpath (Join-Path $BuildDirectory 'work') --specpath $BuildDirectory `
    --collect-all satpy --collect-all pyspectral --collect-all rasterio --collect-data pyresample --collect-data trollimage `
    --collect-data donfig --collect-data imageio_ffmpeg `
    --collect-all cupy --collect-all cupy_backends --collect-all cuda.pathfinder --collect-all nvidia.cuda_runtime --collect-all nvidia.cuda_nvrtc `
    --hidden-import rasterio.sample --hidden-import rasterio.vrt --hidden-import netCDF4 --hidden-import graphlib `
    --hidden-import ges.earth_validation.satpy_execution `
    --hidden-import ges.earth_validation.bounded_readers `
    --exclude-module PySide6 --exclude-module PyQt5 --exclude-module IPython --exclude-module notebook --exclude-module pytest `
    --add-data ((Join-Path $projectRoot 'ges\earth_validation\satpy_config')+';ges/earth_validation/satpy_config') `
    --add-data ((Join-Path $projectRoot 'ges\earth_validation\satpy_execution.py')+';ges/earth_validation') `
    --add-data ((Join-Path $projectRoot 'data\raw\reference\pyspectral')+';data/raw/reference/pyspectral') `
    --add-data ((Join-Path $projectRoot 'data\raw\reference\satpy_geocolor_v060')+';data/raw/reference/satpy_geocolor_v060') `
    --add-data ((Join-Path $projectRoot 'scripts\blender_stock_validation.py')+';scripts') `
    --add-data ((Join-Path $projectRoot 'scripts\blender_sequence_tasks.py')+';scripts') `
    --add-data ((Join-Path $projectRoot 'scripts\blender_gpu_render.py')+';scripts') `
    --add-data ((Join-Path $projectRoot 'scripts\blender_native_earth.py')+';scripts') `
    --add-data ((Join-Path $projectRoot 'scripts\blender_support')+';scripts/blender_support') `
    (Join-Path $projectRoot 'scripts\scientific_engine.py')
if ($LASTEXITCODE -ne 0) { throw 'Scientific engine packaging failed.' }
& (Join-Path $PSScriptRoot 'publish_gpu_launcher.ps1') -EngineDirectory (Join-Path $OutputDirectory 'EarthScience.Engine')
