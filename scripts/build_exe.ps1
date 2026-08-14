<#
.SYNOPSIS
    Build BeadStudio as a onefile windowed EXE with PyInstaller.

.DESCRIPTION
    W4 packaging script (idempotent, re-runnable):

      * onefile, windowed (no console), app icon
      * --add-data "beadstudio/core/data;beadstudio/core/data" mirrors the
        source layout into _MEIPASS, so palette.py's frozen __file__
        (_MEIPASS/beadstudio/core/palette.py) resolves palettes at
        _MEIPASS/beadstudio/core/data/palettes WITHOUT touching core code
      * --add-data "assets;assets" mirrors assets to _MEIPASS/assets,
        matching app.py's Path(__file__).parent.parent / "assets"

    Output: dist\BeadStudio.exe (PySide6 -> roughly 80-120 MB).
    Verify the frozen bundle with:
        dist\BeadStudio.exe --list-brands   (expect: list-brands=21)
#>
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $RepoRoot

# PyInstaller lives in the beadGUI conda env. Invoke it through the env's
# python directly: `conda run` deadlocks on this machine once the child
# emits large output (its temp-file capture races the child's writes), so
# conda run is deliberately avoided here.
$EnvPython = 'D:\Spyder\envs\beadGUI\python.exe'
if (-not (Test-Path -LiteralPath $EnvPython)) {
    throw "beadGUI env python not found: $EnvPython"
}

$PyInstallerArgs = @(
    '--noconfirm'
    '--clean'
    '--onefile'
    '--windowed'
    '--name', 'BeadStudio'
    '--icon', 'assets\app_icon.ico'
    '--add-data', 'beadstudio/core/data;beadstudio/core/data'
    '--add-data', 'assets;assets'
    # conda-python DLLs that PyInstaller's dependency resolver misses:
    # _ctypes.pyd needs ffi.dll, _ssl.pyd needs libssl-3-x64.dll,
    # _bz2.pyd needs libbz2.dll, _sqlite3.pyd needs sqlite3.dll. Without
    # them the frozen app dies during Python init (pyimod03_ctypes).
    '--add-binary', 'D:\Spyder\envs\beadGUI\Library\bin\ffi.dll;.'
    '--add-binary', 'D:\Spyder\envs\beadGUI\Library\bin\libssl-3-x64.dll;.'
    '--add-binary', 'D:\Spyder\envs\beadGUI\Library\bin\libbz2.dll;.'
    '--add-binary', 'D:\Spyder\envs\beadGUI\Library\bin\sqlite3.dll;.'
    'beadstudio\__main__.py'
)

& $EnvPython -m PyInstaller @PyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

$Exe = Join-Path $RepoRoot 'dist\BeadStudio.exe'
if (-not (Test-Path -LiteralPath $Exe)) {
    throw "PyInstaller exited 0 but $Exe was not produced"
}
$SizeMB = [math]::Round((Get-Item -LiteralPath $Exe).Length / 1MB, 1)
Write-Host "OK: $Exe ($SizeMB MB)"
