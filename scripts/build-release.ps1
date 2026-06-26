# Packages Arch Helper for GitHub Releases (ZIP without .venv or local junk).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Version = (Get-Content (Join-Path $Root "VERSION") -Raw).Trim()
$OutDir = Join-Path $Root "dist"
$ZipName = "arch-helper-v$Version-windows.zip"
$ZipPath = Join-Path $OutDir $ZipName
$Stage = Join-Path $OutDir "stage-arch-helper-v$Version"

if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Path $Stage -Force | Out-Null
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$ExcludeDirs = @(
    ".git", ".venv", ".worktrees", "node_modules", "dist", "screenshots", "logs",
    "__pycache__", ".cursor", "agent-transcripts", "uploads"
)

robocopy $Root $Stage /E /NFL /NDL /NJH /NJS /nc /ns /np `
    /XD $ExcludeDirs `
    /XF *.pyc *.pyo *.log STOP .env | Out-Null

Copy-Item (Join-Path $Root "release\Install.cmd") (Join-Path $Stage "Install.cmd") -Force
Copy-Item (Join-Path $Root "release\Start-Panel.cmd") (Join-Path $Stage "Start-Panel.cmd") -Force
Copy-Item (Join-Path $Root "release\Run-Bot.cmd") (Join-Path $Stage "Run-Bot.cmd") -Force
Copy-Item (Join-Path $Root "release\INSTALLATION.md") (Join-Path $Stage "INSTALLATION.md") -Force

$dataDir = Join-Path $Stage "data"
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
if (-not (Test-Path (Join-Path $dataDir "presets.json"))) {
    Copy-Item (Join-Path $Root "config\presets.json") (Join-Path $dataDir "presets.json") -Force
}

if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath -Force
Remove-Item $Stage -Recurse -Force

Write-Host "Release ready: $ZipPath"
Write-Host "Version: $Version"
