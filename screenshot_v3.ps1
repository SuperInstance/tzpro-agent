param([string]$OutDir, [string]$Filename)
$path = Join-Path $OutDir $Filename
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap(1920, 1080)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$size = New-Object System.Drawing.Size(1920, 1080)
$g.CopyFromScreen(1920, 0, 0, 0, $size)
$g.Dispose()
$bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output $path
