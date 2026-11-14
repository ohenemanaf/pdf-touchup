# Copies the English OCR data into packaging/vendor/tesseract/tessdata.
# PyMuPDF has the Tesseract engine built in, so only the language file is bundled.
param([string]$Source = "C:\Program Files\Tesseract-OCR\tessdata")
$ErrorActionPreference = "Stop"
$dest = Join-Path $PSScriptRoot "vendor\tesseract\tessdata"
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item (Join-Path $Source "eng.traineddata") $dest -Force
Write-Host "Copied eng.traineddata to $dest"
