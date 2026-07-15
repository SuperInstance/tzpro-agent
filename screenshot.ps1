# capture_monitor2.ps1 — Capture the second monitor (TZ Pro feed)
# DISPLAY6 = 1920x1080 at X=1920, Y=0
param(
    [string]$OutputPath = "$PSScriptRoot\captures"
)

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$filename = "tzpro_$ts.png"
$fullPath = Join-Path $OutputPath $filename

# Ensure output directory exists
if (-not (Test-Path $OutputPath)) {
    New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null
}

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

# Capture region: second monitor bounds
$x = 1920
$y = 0
$width = 1920
$height = 1080

$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($x, $y, 0, 0, $bitmap.Size)
$graphics.Dispose()
$bitmap.Save($fullPath, [System.Drawing.Imaging.ImageFormat]::Png)
$bitmap.Dispose()

Write-Output $fullPath
