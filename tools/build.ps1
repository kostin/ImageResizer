<#
.SYNOPSIS
    Сборка ImageResizer.exe — одного исполняемого файла для Windows.

.DESCRIPTION
    Проверяет зависимости, прогоняет тесты и собирает dist\ImageResizer.exe
    через PyInstaller. Внутрь файла упакованы Python и Pillow, поэтому на
    целевой машине ничего устанавливать не нужно.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\build.ps1

.EXAMPLE
    pwsh -File tools\build.ps1 -Python "C:\Python312\python.exe" -SkipTests
#>
[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$SkipTests,
    [switch]$NoClean
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    Write-Host "== Зависимости ==" -ForegroundColor Cyan
    & $Python -c "import PIL, PyInstaller" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Устанавливаю зависимости из requirements.txt..." -ForegroundColor Yellow
        & $Python -m pip install --upgrade -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw "Не удалось установить зависимости" }
    }

    if (-not $SkipTests) {
        Write-Host "== Тесты ==" -ForegroundColor Cyan
        & $Python -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) { throw "Тесты не прошли, сборка остановлена" }
    }

    Write-Host "== Сборка одного exe ==" -ForegroundColor Cyan
    $pyinstallerArgs = @("-m", "PyInstaller", "--noconfirm")
    if (-not $NoClean) { $pyinstallerArgs += "--clean" }
    $pyinstallerArgs += "ImageResizer.spec"
    & $Python @pyinstallerArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с ошибкой" }

    $exe = Join-Path $projectRoot "dist\ImageResizer.exe"
    if (-not (Test-Path -LiteralPath $exe)) { throw "Не найден $exe" }

    Write-Host ""
    Write-Host ("Собрано: {0} ({1:N1} МБ)" -f $exe, ((Get-Item -LiteralPath $exe).Length / 1MB)) -ForegroundColor Green

    # Проверка, что exe реально стартует. Если папка помечена низким уровнем
    # целостности (Low IL), PyInstaller не сможет распаковаться в %TEMP%,
    # и программа закроется сразу после запуска.
    Write-Host "== Проверка запуска ==" -ForegroundColor Cyan
    $probe = ""
    try {
        $probe = (& $exe --help 2>&1 | Out-String)
    } catch {
        $probe = $_.Exception.Message
    }
    if ($LASTEXITCODE -eq 0 -and $probe -match "usage") {
        Write-Host "Exe запускается, справка отвечает." -ForegroundColor Green
    } else {
        Write-Warning "Exe не запустился в этой папке. Ответ: $($probe.Trim())"
        Write-Warning "Похоже, папка помечена низким уровнем целостности (Low IL): тогда процесс не может писать в %TEMP%."
        Write-Warning "Скопируйте exe в обычную папку (например, Загрузки) — там он запустится."
        $rescue = Join-Path $env:USERPROFILE "Downloads\ImageResizer"
        New-Item -ItemType Directory -Force -Path $rescue | Out-Null
        Copy-Item -LiteralPath $exe -Destination (Join-Path $rescue "ImageResizer.exe") -Force
        Write-Host ("Рабочая копия скопирована: {0}" -f (Join-Path $rescue "ImageResizer.exe")) -ForegroundColor Yellow
    }
}
finally {
    Pop-Location
}
