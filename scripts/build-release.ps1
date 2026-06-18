# Empaqueta Arch Helper para GitHub Releases (ZIP sin .venv ni basura local).
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

Copy-Item (Join-Path $Root "release\Instalar.cmd") (Join-Path $Stage "Instalar.cmd") -Force
Copy-Item (Join-Path $Root "release\Iniciar-Panel.cmd") (Join-Path $Stage "Iniciar-Panel.cmd") -Force
Copy-Item (Join-Path $Root "release\LEEME-INSTALACION.md") (Join-Path $Stage "LEEME-INSTALACION.md") -Force

if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath -Force
Remove-Item $Stage -Recurse -Force

Write-Host "Release listo: $ZipPath"
Write-Host "Version: $Version"
