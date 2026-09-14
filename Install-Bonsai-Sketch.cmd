@echo off
setlocal
set "SKETCH_INSTALLER_FILE=%~f0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$text = [IO.File]::ReadAllText($env:SKETCH_INSTALLER_FILE); & ([scriptblock]::Create(($text -split ('# POWER' + 'SHELL_PAYLOAD'), 2)[1]))"
set "INSTALL_RESULT=%ERRORLEVEL%"
if not "%SKETCH_INSTALL_CHECK_ONLY%"=="1" pause
exit /b %INSTALL_RESULT%
# POWERSHELL_PAYLOAD
# Embedded into Install-Bonsai-Sketch.cmd by build_windows_installer.py.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

function Invoke-Blender {
    param([string[]]$Arguments)
    & $script:BlenderPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Blender failed (exit $LASTEXITCODE). See the output above."
    }
}

try {
    Write-Host 'Bonsai Sketch Mode installer' -ForegroundColor Cyan
    if (Get-Process blender -ErrorAction SilentlyContinue) {
        throw 'Save your work and close Blender, then run this installer again.'
    }

    $candidates = @()
    if ($env:BLENDER_EXE) {
        $candidates += $env:BLENDER_EXE
    } else {
        $onPath = Get-Command blender.exe -ErrorAction SilentlyContinue
        if ($onPath) { $candidates += $onPath.Source }
        foreach ($base in @($env:ProgramFiles, $env:LOCALAPPDATA)) {
            if ($base) {
                $candidates += @(Get-ChildItem -Path "$base/Blender Foundation/Blender */blender.exe" -ErrorAction SilentlyContinue | ForEach-Object FullName)
            }
        }
    }
    $supported = @(foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $versionOutput = & $candidate --version 2>&1
            if ($LASTEXITCODE -eq 0 -and ($versionOutput -join "`n") -match 'Blender (5\.(?:0|2)\.\d+)') {
                [PSCustomObject]@{ Path = $candidate; Version = [version]$Matches[1] }
            }
        }
    })
    if (!$supported.Count) {
        throw 'Install Blender 5.0 or 5.2 from https://www.blender.org/download/ first. For a portable install, set BLENDER_EXE to its blender.exe path.'
    }
    $chosen = $supported | Sort-Object Version -Descending | Select-Object -First 1
    $script:BlenderPath = $chosen.Path
    Write-Host "Using Blender $($chosen.Version): $BlenderPath"
    if ($env:SKETCH_INSTALL_CHECK_ONLY -eq '1') {
        Write-Host 'Installer check passed. No downloads or changes were made.'
        exit 0
    }

    $work = Join-Path ([IO.Path]::GetTempPath()) ('bonsai-sketch-install-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $work | Out-Null
    Write-Host "Installation files and logs: $work"
    Start-Transcript -Path (Join-Path $work 'install.log') | Out-Null
    # Refuse a legacy duplicate or a development link before modifying packages.
    $preflight = @'
import bpy, os, stat
for addon in bpy.context.preferences.addons:
    if addon.module.split('.')[-1] == 'bonsaibim_sketch_mode':
        raise RuntimeError('Remove the old BonsaiBIM Sketch Mode add-on in Preferences first, then rerun this installer.')
for repo in bpy.context.preferences.extensions.repos:
    path = os.path.join(repo.directory, 'bonsai_sketch_mode')
    if os.path.lexists(path) and (os.path.islink(path) or getattr(os.lstat(path), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise RuntimeError('Sketch Mode uses a development link. Remove that link before installing a release.')
'@
    Invoke-Blender @('--background', '--python-exit-code', '1', '--python-expr', $preflight)
    $installerDir = Split-Path -Parent $env:SKETCH_INSTALLER_FILE
    $source = Join-Path $installerDir 'bonsai_sketch_mode'
    if (Test-Path -LiteralPath (Join-Path $source 'blender_manifest.toml')) {
        Write-Host 'Building Sketch Mode from this checkout...'
        Invoke-Blender @('--command', 'extension', 'build', '--source-dir', $source, '--output-dir', $work)
        $packages = @(Get-ChildItem -LiteralPath $work -Filter 'bonsai_sketch_mode-*.zip')
        if ($packages.Count -ne 1) { throw 'Expected exactly one built extension ZIP.' }
        $package = $packages[0].FullName
    } else {
        Write-Host 'Downloading the latest Sketch Mode release...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/integrations-space/BonsaiSketch/releases/latest' -Headers @{ 'User-Agent' = 'Bonsai-Sketch-Installer' }
        $assets = @($release.assets | Where-Object { $_.name -match '^bonsai_sketch_mode-\d+\.\d+\.\d+\.zip$' })
        if ($assets.Count -ne 1) { throw 'The latest release must contain exactly one versioned Sketch Mode extension ZIP.' }
        $package = Join-Path $work $assets[0].name
        Invoke-WebRequest -UseBasicParsing -Uri $assets[0].browser_download_url -OutFile $package
        if ($assets[0].PSObject.Properties.Name -contains 'digest' -and $assets[0].digest) {
            $actual = 'sha256:' + (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne $assets[0].digest) { throw 'The release download checksum does not match. Run the installer again.' }
        }
    }
    Invoke-Blender @('--command', 'extension', 'validate', $package)
    Write-Host 'Installing and enabling Bonsai from the official Blender repository...'
    Invoke-Blender @('--online-mode', '--command', 'extension', 'install', 'bonsai', '--sync', '--enable')
    Write-Host 'Installing and enabling Bonsai Sketch Mode...'
    Invoke-Blender @('--command', 'extension', 'install-file', '--repo', 'user_default', '--enable', $package)
    $verify = @'
import bpy, addon_utils
for name in ('bonsai', 'bonsai_sketch_mode'):
    modules = [a.module for a in bpy.context.preferences.addons if a.module.split('.')[-1] == name]
    if not modules or not any(addon_utils.check(m)[1] for m in modules):
        raise RuntimeError(name + ' did not load. Check the Blender errors above.')
print('Bonsai and Sketch Mode are enabled and loaded.')
'@
    Invoke-Blender @('--background', '--python-exit-code', '1', '--python-expr', $verify)
    Write-Host 'Installation complete. Open Blender and select the Sketch tab.' -ForegroundColor Green
    Stop-Transcript | Out-Null
    exit 0
} catch {
    Write-Host "Installation stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Any completed installation steps remain in place. You can run this installer again.'
    exit 1
}
