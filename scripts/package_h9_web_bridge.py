"""Package local bridge helpers without copying or changing native weather."""
from pathlib import Path
import shutil

root=Path(__file__).resolve().parents[1]
out=root/'data/exports/H9_20261020_WebBridge_v1'
helpers=out/'tools';helpers.mkdir(parents=True,exist_ok=True)
for src,name in [('scripts/blender_import_dynamic_cameras.py','import_web_camera.py'),('scripts/blender_support/editable_camera.py','editable_camera.py'),('ges_next/camera.py','camera_contract.py')]:
    shutil.copy2(root/src,helpers/name)
shutil.copy2(root/'scripts/blender_preview_modes.py',helpers/'blender_preview_modes.py')
for src,name in [('reports/h9_web_bridge/actual_browser_bundle.json','双分镜验收示例.json'),('reports/h9_web_bridge/blender_verification/verification.json','实际浏览器至Blender验证.json')]:
    shutil.copy2(root/src,out/name)
(out/'导入网页分镜.ps1').write_text('''param([string]$CameraJson,[switch]$CheckOnly,[switch]$NoOpen,[ValidateSet('11K','22K')][string]$TextureMode='11K')
$ErrorActionPreference='Stop'
if($TextureMode -eq '11K'){
 $base=Join-Path $PSScriptRoot '..\\H9_20261020_12h_Blender_11K_v1'
 $blend=Join-Path $base 'Earth_Studio_11K_清晰构图版.blend'
}else{
 $base=Join-Path $PSScriptRoot '..\\H9_20261020_12h_Blender_v1'
 $blend=Join-Path $base 'Earth_Studio_动态天气与自由运镜.blend'
}
$blender='D:\\Softwares\\Blender\\blender.exe'
foreach($dependency in @($blend,$blender,(Join-Path $PSScriptRoot 'tools\\import_web_camera.py'))){
 if(-not(Test-Path -LiteralPath $dependency)){throw "Missing dependency: $dependency"}
}
if($CheckOnly){Write-Output "IMPORT_ENTRY_READY $TextureMode";return}
if(-not $CameraJson){
 Add-Type -AssemblyName System.Windows.Forms
 $dialog=New-Object System.Windows.Forms.OpenFileDialog
 $dialog.Title='选择网页导出的相机 JSON';$dialog.Filter='Camera JSON (*.json)|*.json'
 try{if($dialog.ShowDialog() -ne 'OK'){return};$CameraJson=$dialog.FileName}finally{$dialog.Dispose()}
}
$inputFile=(Resolve-Path -LiteralPath $CameraJson).Path
$target=Join-Path $base ('user_projects\\'+[IO.Path]::GetFileNameWithoutExtension($inputFile)+'_'+$TextureMode+'_'+(Get-Date -Format 'yyyyMMdd_HHmmss')+'.blend')
& $blender --background $blend --disable-autoexec --python-exit-code 1 --python (Join-Path $PSScriptRoot 'tools\\import_web_camera.py') -- $inputFile $target
if($LASTEXITCODE -ne 0){throw 'Import failed; review the error above.'}
if(-not $NoOpen){
 $launch=@('"'+$target+'"','--disable-autoexec')
 if($TextureMode -eq '11K'){$launch+=@('--python','"'+(Join-Path $PSScriptRoot 'tools\\blender_preview_modes.py')+'"')}
 Start-Process -FilePath $blender -ArgumentList $launch
}
''',encoding='utf-8-sig')
(out/'启动动态摄影棚.ps1').write_text('''param([switch]$CheckOnly)
$ErrorActionPreference='Stop'
$repo=(Resolve-Path (Join-Path $PSScriptRoot '..\\..\\..')).Path
$python=Join-Path $repo '..\\GlobalSatelliteEarthStudio\\.venv\\Scripts\\python.exe'
foreach($dependency in @($python,(Join-Path $repo 'data\\cesium_h9_motion_20261020\\manifest.json'))){
 if(-not(Test-Path -LiteralPath $dependency)){throw "Missing dependency: $dependency"}
}
if($CheckOnly){Write-Output 'STUDIO_ENTRY_READY';return}
if(-not (Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue)){
 Start-Process -FilePath $python -ArgumentList @('-X','utf8','-u','-m','ges_next.preview_server','--materials','data/cesium_h9_motion_20261020','--port','8766') -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'preview.stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'preview.stderr.log')
}
Start-Process 'http://127.0.0.1:8766/?manifest=/data/manifest.json'
''',encoding='utf-8-sig')
shutil.copy2(out/'导入网页分镜.ps1',out/'Import_Camera.ps1')
shutil.copy2(out/'启动动态摄影棚.ps1',out/'Open_Studio.ps1')
for name,arg in [('Import_Camera',' "%~1"'),('Open_Studio','')]:
    (out/(name+'.cmd')).write_text('@echo off\r\npowershell.exe -NoProfile -File "%~dp0'+name+'.ps1"'+arg+'\r\nif errorlevel 1 pause\r\n',encoding='ascii')
for mode in ['11K','22K']:
    (out/('Import_Camera_'+mode+'.cmd')).write_text('@echo off\r\npowershell.exe -NoProfile -File "%~dp0Import_Camera.ps1" "%~1" -TextureMode '+mode+'\r\nif errorlevel 1 pause\r\n',encoding='ascii')
(out/'Open_My_11K.ps1').write_text('''param([switch]$CheckOnly)
$ErrorActionPreference='Stop'
$blend=Join-Path $PSScriptRoot '..\\H9_20261020_12h_Blender_11K_v1\\user_projects\\我的运镜_11K清晰构图版.blend'
$helper=Join-Path $PSScriptRoot 'tools\\blender_preview_modes.py'
$blender='D:\\Softwares\\Blender\\blender.exe'
foreach($file in @($blend,$helper,$blender)){if(-not(Test-Path -LiteralPath $file)){throw "Missing dependency: $file"}}
if($CheckOnly){Write-Output 'CLEAR_PREVIEW_ENTRY_READY';return}
Start-Process -FilePath $blender -ArgumentList @('"'+$blend+'"','--disable-autoexec','--python','"'+$helper+'"')
''',encoding='utf-8-sig')
(out/'Open_My_11K.cmd').write_text('@echo off\r\npowershell.exe -NoProfile -File "%~dp0Open_My_11K.ps1"\r\nif errorlevel 1 pause\r\n',encoding='ascii')
shutil.copy2(root/'docs/H9_DYNAMIC_WEB_BRIDGE.md',out/'使用说明.md')
print(out)
