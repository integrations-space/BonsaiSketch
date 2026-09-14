"""Build a standalone Windows launcher; no Python is needed by end users."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = '''@echo off
setlocal
set "SKETCH_INSTALLER_FILE=%~f0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$text = [IO.File]::ReadAllText($env:SKETCH_INSTALLER_FILE); & ([scriptblock]::Create(($text -split '# POWERSHELL_PAYLOAD', 2)[1]))"
set "INSTALL_RESULT=%ERRORLEVEL%"
if not "%SKETCH_INSTALL_CHECK_ONLY%"=="1" pause
exit /b %INSTALL_RESULT%
# POWERSHELL_PAYLOAD
'''


def build():
    payload = (ROOT / 'tools/windows_installer.ps1').read_text(encoding='utf-8')
    # The marker also occurs in the command; concatenate it there to keep the
    # delimiter unique when the launcher reads itself.
    header = HEADER.replace("-split '# POWERSHELL_PAYLOAD'", "-split ('# POWER' + 'SHELL_PAYLOAD')")
    target = ROOT / 'Install-Bonsai-Sketch.cmd'
    target.write_bytes((header + payload).replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8'))
    return target


if __name__ == '__main__':
    print(build())
