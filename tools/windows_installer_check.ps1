# Offline orchestration tests: no downloads, Blender installs or user preferences.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('sketch-installer-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$fake = Join-Path $testRoot 'fake blender.ps1'
@'
Add-Content -LiteralPath $env:SKETCH_TEST_LOG -Value ($args | ConvertTo-Json -Compress)
if ($args -contains '--version') { Write-Output "Blender $env:SKETCH_TEST_VERSION"; exit 0 }
if ($env:SKETCH_TEST_FAIL -and $args -contains $env:SKETCH_TEST_FAIL) { exit 7 }
if ($args -contains 'build') {
    $dest = $args[[Array]::IndexOf($args, '--output-dir') + 1]
    Set-Content -LiteralPath (Join-Path $dest 'bonsai_sketch_mode-0.4.0.zip') -Value 'fixture'
}
exit 0
'@ | Set-Content -LiteralPath $fake
$runner = Join-Path $testRoot 'runner.ps1'
@'
function Get-Process { if ($env:SKETCH_TEST_RUNNING -eq '1') { 'blender' } }
function Invoke-RestMethod {
    $name = if ($env:SKETCH_TEST_BAD_RELEASE -eq '1') { 'source.zip' } else { 'bonsai_sketch_mode-0.4.0.zip' }
    return @{ assets = @(@{ name = $name; browser_download_url = 'https://example.invalid/package.zip' }) }
}
function Invoke-WebRequest { param([switch]$UseBasicParsing, $Uri, $OutFile) Set-Content -LiteralPath $OutFile -Value 'fixture' }
& $env:SKETCH_TEST_PAYLOAD
exit $LASTEXITCODE
'@ | Set-Content -LiteralPath $runner

$env:BLENDER_EXE = $fake
$env:SKETCH_INSTALLER_FILE = Join-Path $testRoot 'Install-Bonsai-Sketch.cmd'
$env:SKETCH_TEST_PAYLOAD = Join-Path $PSScriptRoot 'windows_installer.ps1'
$env:SKETCH_TEST_LOG = Join-Path $testRoot 'calls.jsonl'
$env:SKETCH_TEST_VERSION = '5.2.0'
$env:SKETCH_INSTALL_CHECK_ONLY = ''

function Run-Case([string]$Name, [int]$Expected, [string]$Message) {
    Set-Content -LiteralPath $env:SKETCH_TEST_LOG -Value ''
    $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner 2>&1
    if ($LASTEXITCODE -ne $Expected -or ($output -join "`n") -notmatch [regex]::Escape($Message)) {
        throw "$Name failed: $output"
    }
    Write-Host "PASS: $Name"
}

Run-Case 'release installation' 0 'Installation complete'
$calls = Get-Content -LiteralPath $env:SKETCH_TEST_LOG -Raw
if ($calls -notmatch 'install-file' -or $calls -notmatch '--sync' -or $calls -notmatch 'addon_utils') { throw 'Missing installation or verification step.' }

New-Item -ItemType Directory -Path (Join-Path $testRoot 'bonsai_sketch_mode') | Out-Null
Set-Content -LiteralPath (Join-Path $testRoot 'bonsai_sketch_mode/blender_manifest.toml') -Value 'fixture'
Run-Case 'checkout installation' 0 'Building Sketch Mode from this checkout'
$env:SKETCH_TEST_FAIL = 'validate'
Run-Case 'invalid package stops installation' 1 'Blender failed (exit 7)'
if ((Get-Content -LiteralPath $env:SKETCH_TEST_LOG -Raw) -match '--sync|install-file') { throw 'Installed after validation failure.' }
$env:SKETCH_TEST_FAIL = '--python-expr'
Run-Case 'preflight failure stops installation' 1 'Blender failed (exit 7)'
if ((Get-Content -LiteralPath $env:SKETCH_TEST_LOG -Raw) -match 'install-file|--sync') { throw 'Installed after preflight failure.' }
$env:SKETCH_TEST_FAIL = ''
$env:SKETCH_TEST_VERSION = '5.3.0'
Run-Case 'unsupported Blender' 1 'Install Blender 5.0 or 5.2'
$env:SKETCH_TEST_VERSION = '5.2.0'
$env:SKETCH_TEST_RUNNING = '1'
Run-Case 'running Blender' 1 'Save your work and close Blender'
$env:SKETCH_TEST_RUNNING = ''
$env:SKETCH_INSTALLER_FILE = Join-Path $testRoot 'standalone/Install-Bonsai-Sketch.cmd'
$env:SKETCH_TEST_BAD_RELEASE = '1'
Run-Case 'missing release asset' 1 'exactly one versioned'
$env:SKETCH_TEST_BAD_RELEASE = ''
$env:SKETCH_INSTALL_CHECK_ONLY = '1'
& (Join-Path $root 'Install-Bonsai-Sketch.cmd')
if ($LASTEXITCODE -ne 0) { throw 'Standalone launcher failed.' }
Write-Host 'PASS: standalone launcher'
Write-Host "Test evidence: $testRoot"
