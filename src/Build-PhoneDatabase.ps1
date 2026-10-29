[CmdletBinding()]
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$DatabasePath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'phones.duckdb'),
    [switch]$RefreshCna
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'PhoneDatabase.psm1') -Force
Initialize-PhoneDatabase $DatabasePath | Out-Null
Import-DfrpXml -XmlPath (Join-Path $Root 'dfrp-rbif.xml') -DatabasePath $DatabasePath
$cna = Join-Path $Root 'data/raw/cna/COCodeStatus_ALL.csv'
if ($RefreshCna -or -not (Test-Path $cna)) {
    $zip = Join-Path $Root 'data/raw/cna/COCodeStatus_ALL.zip'
    Invoke-WebRequest -Uri 'https://www.cnac.ca/data/COCodeStatus_ALL.zip' -OutFile $zip
    Expand-Archive -Force -Path $zip -DestinationPath (Split-Path $cna)
}
Import-CnaCoCodes -CsvPath $cna -DatabasePath $DatabasePath
Write-Host "Database ready: $DatabasePath"
