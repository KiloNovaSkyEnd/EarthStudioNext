param([Parameter(Mandatory=$true)][string]$OutputDirectory, [string]$ReadmeDocument = 'docs/NATIVE_DESKTOP_M1.md')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$releaseDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $releaseDirectory) {
    throw 'Choose a new output directory; existing releases are never replaced.'
}
dotnet publish (Join-Path $projectRoot 'native/EarthStudio.App/EarthStudio.App.csproj') -c Release -r win-x64 --self-contained true -o $releaseDirectory
if ($LASTEXITCODE -ne 0) { throw 'Native publish failed.' }
Copy-Item -LiteralPath (Join-Path $projectRoot $ReadmeDocument) -Destination (Join-Path $releaseDirectory 'README.md')
Write-Output (Join-Path $releaseDirectory 'EarthStudio.App.exe')
