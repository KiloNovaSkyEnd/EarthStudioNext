param([Parameter(Mandatory=$true)][string]$EngineDirectory)
$ErrorActionPreference='Stop'
$engineRoot=(Resolve-Path -LiteralPath $EngineDirectory).Path
$original=Join-Path $engineRoot 'EarthScience.Engine.exe'
$cuda=Join-Path $engineRoot 'EarthScience.Cuda.exe'
if(Test-Path -LiteralPath $cuda){throw 'Existing CUDA executable preserved; use a new build directory.'}
$compiler=Join-Path ([Environment]::GetFolderPath('Windows')) 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if(-not(Test-Path -LiteralPath $compiler)){throw 'Windows .NET Framework C# compiler unavailable'}
# Both resolved move paths are confined to the explicitly requested engine folder.
if([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($original)) -ne $engineRoot -or
   [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($cuda)) -ne $engineRoot){throw 'Invalid engine move'}
Move-Item -LiteralPath $original -Destination $cuda
& $compiler /nologo /target:exe /platform:x64 "/out:$original" (Join-Path $PSScriptRoot 'GpuEngineLauncher.cs')
if($LASTEXITCODE -ne 0){throw 'GPU launcher compilation failed; CUDA executable preserved'}
