#requires -Version 5.1
<#
.SYNOPSIS
Build an unsigned x64 MSIX with a strict payload allowlist.
.DESCRIPTION
Run with -DevelopmentIdentity for packaging tests only. For Store submissions,
copy IdentityName, Publisher and PublisherDisplayName from Partner Center.
This script does not install packages, certificates, or submit anything.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$IdentityName,
    [string]$Publisher,
    [string]$PublisherDisplayName,
    [string]$DisplayName = '轻记',
    [switch]$DevelopmentIdentity,
    [string]$Executable,
    [string]$MakeAppx
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = Split-Path -Parent $PSScriptRoot

if ($env:OS -ne 'Windows_NT') { throw 'MSIX packaging requires Windows.' }
if ($Version -notmatch '^([1-9][0-9]*)\.([0-9]+)\.([0-9]+)\.0$' -or
    @($Version.Split('.') | Where-Object { [long]$_ -gt 65535 }).Count -gt 0) {
    throw 'Version must be Major.Minor.Build.0; each component is 0..65535 and Major is 1 or greater.'
}
if ($DevelopmentIdentity) {
    if ($IdentityName -or $Publisher -or $PublisherDisplayName) {
        throw 'Do not combine -DevelopmentIdentity with Partner Center identity values.'
    }
    $IdentityName = 'QuickMemory.Development'
    $Publisher = 'CN=QuickMemory Development'
    $PublisherDisplayName = 'QuickMemory Development'
} elseif (-not $IdentityName -or -not $Publisher -or -not $PublisherDisplayName) {
    throw 'Provide -IdentityName, -Publisher and -PublisherDisplayName from Partner Center, or explicitly use -DevelopmentIdentity.'
}
if ($IdentityName -notmatch '^[A-Za-z0-9][A-Za-z0-9.-]{2,49}$') {
    throw 'IdentityName must be a valid 3..50 character MSIX identity name.'
}
if (-not $Executable) { $Executable = Join-Path $projectRoot 'dist\QuickMemory.exe' }
$Executable = (Resolve-Path -LiteralPath $Executable).Path
foreach ($required in @('LICENSE', 'assets\quickmemory.ico', 'dist\THIRD_PARTY_NOTICES.txt', 'docs\PRIVACY.md')) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $required) -PathType Leaf)) {
        throw "Missing $required. Build the Windows EXE and collect third-party notices first."
    }
}
# Reject a mislabeled architecture before assembling the package.
$stream = [IO.File]::OpenRead($Executable)
$reader = [IO.BinaryReader]::new($stream)
try {
    if ($reader.ReadUInt16() -ne 0x5a4d) { throw 'Executable is not a Windows PE file.' }
    $stream.Position = 0x3c
    $peOffset = $reader.ReadUInt32()
    $stream.Position = $peOffset
    if ($reader.ReadUInt32() -ne 0x4550 -or $reader.ReadUInt16() -ne 0x8664) {
        throw 'This package recipe requires an x64 Windows executable.'
    }
} finally { $reader.Dispose(); $stream.Dispose() }

if (-not $MakeAppx) {
    $command = Get-Command 'makeappx.exe' -ErrorAction SilentlyContinue
    if ($command) { $MakeAppx = $command.Source }
}
if (-not $MakeAppx) {
    $sdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
    $candidates = @(Get-ChildItem -LiteralPath $sdkRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^10\.0\.\d+\.\d+$' } |
        Sort-Object { [version]$_.Name } -Descending)
    foreach ($sdk in $candidates) {
        $candidate = Join-Path $sdk.FullName 'x64\makeappx.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { $MakeAppx = $candidate; break }
    }
}
if (-not $MakeAppx -or -not (Test-Path -LiteralPath $MakeAppx -PathType Leaf)) {
    throw 'MakeAppx.exe was not found. Install Windows SDK or pass -MakeAppx with its full path.'
}

# A new staging directory prevents stale files/user data from a previous build.
# Never copy the project directory, dist directory, database, logs, or credentials.
$buildRoot = Join-Path $projectRoot 'build\msix'
$outputRoot = Join-Path $projectRoot 'dist\msix'
$stage = Join-Path $buildRoot ([guid]::NewGuid().ToString('N'))
$assets = Join-Path $stage 'Assets'
New-Item -ItemType Directory -Path $assets, $outputRoot -Force | Out-Null
$reportPath = Join-Path $buildRoot ('self-test-' + [guid]::NewGuid().ToString('N') + '.json')
$startInfo = [Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = $Executable
$startInfo.Arguments = '--self-test "' + $reportPath + '"'
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.WorkingDirectory = $projectRoot
$check = [Diagnostics.Process]::Start($startInfo)
try {
    if (-not $check.WaitForExit(90000)) { $check.Kill(); throw 'Frozen self-test timed out.' }
    if ($check.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $reportPath)) {
        throw 'Frozen self-test failed. The MSIX was not produced.'
    }
    $report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($report.ok -ne $true -or $report.checks.frozen -ne $true) {
        throw 'Frozen self-test report was not successful. The MSIX was not produced.'
    }
} finally { $check.Dispose() }

Copy-Item -LiteralPath $Executable -Destination (Join-Path $stage 'QuickMemory.exe')
Copy-Item -LiteralPath (Join-Path $projectRoot 'LICENSE') -Destination $stage
Copy-Item -LiteralPath (Join-Path $projectRoot 'dist\THIRD_PARTY_NOTICES.txt') -Destination $stage
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\PRIVACY.md') -Destination $stage

# Reuse the existing product icon; no remote assets or image-generation service.
Add-Type -AssemblyName System.Drawing
$iconBytes = [IO.File]::ReadAllBytes((Join-Path $projectRoot 'assets\quickmemory.ico'))
$iconCount = [BitConverter]::ToUInt16($iconBytes, 4)
$largest = $null
for ($index = 0; $index -lt $iconCount; $index++) {
    $entry = 6 + 16 * $index
    $width = if ($iconBytes[$entry] -eq 0) { 256 } else { [int]$iconBytes[$entry] }
    $height = if ($iconBytes[$entry + 1] -eq 0) { 256 } else { [int]$iconBytes[$entry + 1] }
    if (-not $largest -or $width * $height -gt $largest.area) {
        $largest = @{
            area = $width * $height
            length = [BitConverter]::ToUInt32($iconBytes, $entry + 8)
            offset = [BitConverter]::ToUInt32($iconBytes, $entry + 12)
        }
    }
}
if (-not $largest -or $largest.offset + $largest.length -gt $iconBytes.Length) {
    throw 'The application icon contains no valid embedded image.'
}
# build_windows.py embeds PNG images inside ICO; loading the PNG directly also
# works on older System.Drawing versions whose Icon.ToBitmap rejects PNG ICOs.
$imageStream = [IO.MemoryStream]::new($iconBytes, $largest.offset, $largest.length)
$source = [Drawing.Image]::FromStream($imageStream)
try {
    foreach ($size in @(44, 50, 150)) {
        $bitmap = [Drawing.Bitmap]::new($size, $size)
        $graphics = [Drawing.Graphics]::FromImage($bitmap)
        try {
            $graphics.Clear([Drawing.Color]::Transparent)
            $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.PixelOffsetMode = [Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $graphics.DrawImage($source, 0, 0, $size, $size)
            $bitmap.Save((Join-Path $assets "Logo$size.png"), [Drawing.Imaging.ImageFormat]::Png)
        } finally { $graphics.Dispose(); $bitmap.Dispose() }
    }
} finally { $source.Dispose(); $imageStream.Dispose() }

function Escape-Xml([string]$value) { return [Security.SecurityElement]::Escape($value) }
$identityXml = Escape-Xml $IdentityName
$publisherXml = Escape-Xml $Publisher
$publisherDisplayXml = Escape-Xml $PublisherDisplayName
$displayXml = Escape-Xml $DisplayName
$manifest = @"
<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         xmlns:uap10="http://schemas.microsoft.com/appx/manifest/uap/windows10/10"
         xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
         IgnorableNamespaces="uap uap10 rescap">
  <Identity Name="$identityXml" Publisher="$publisherXml" Version="$Version" ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>$displayXml</DisplayName>
    <PublisherDisplayName>$publisherDisplayXml</PublisherDisplayName>
    <Description>本地题库、默写练习与 AI 多裁判评分</Description>
    <Logo>Assets\Logo50.png</Logo>
  </Properties>
  <Resources><Resource Language="zh-CN" /></Resources>
  <Dependencies><TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.19041.0" MaxVersionTested="10.0.26200.0" /></Dependencies>
  <Applications>
    <Application Id="QuickMemory" Executable="QuickMemory.exe" uap10:RuntimeBehavior="packagedClassicApp" uap10:TrustLevel="mediumIL">
      <uap:VisualElements DisplayName="$displayXml" Description="本地题库与默写练习" Square150x150Logo="Assets\Logo150.png" Square44x44Logo="Assets\Logo44.png" BackgroundColor="transparent" />
    </Application>
  </Applications>
  <Capabilities><rescap:Capability Name="runFullTrust" /></Capabilities>
</Package>
"@
[IO.File]::WriteAllText((Join-Path $stage 'AppxManifest.xml'), $manifest, [Text.UTF8Encoding]::new($false))
$flavor = if ($DevelopmentIdentity) { 'development-unsigned' } else { 'store-unsigned' }
$output = Join-Path $outputRoot "QuickMemory-$Version-x64-$flavor.msix"
# Keep validation enabled: intentionally do not pass /nv.
& $MakeAppx pack /o /h SHA256 /d $stage /p $output
if ($LASTEXITCODE -ne 0) { throw "MakeAppx failed with exit code $LASTEXITCODE." }

$payload = @(Get-ChildItem -LiteralPath $stage -Recurse -File | ForEach-Object {
    $_.FullName.Substring($stage.Length + 1).Replace('\', '/')
} | Sort-Object)
$metadata = [ordered]@{
    package = [IO.Path]::GetFileName($output)
    sha256 = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
    bytes = (Get-Item -LiteralPath $output).Length
    version = $Version
    architecture = 'x64'
    identity_name = $IdentityName
    publisher = $Publisher
    development_identity = [bool]$DevelopmentIdentity
    signed = $false
    submitted_to_store = $false
    executable_sha256 = (Get-FileHash -LiteralPath $Executable -Algorithm SHA256).Hash.ToLowerInvariant()
    payload = $payload
}
[IO.File]::WriteAllText(($output + '.json'), ($metadata | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
Write-Host "Created unsigned MSIX: $output"
Write-Host "SHA256: $($metadata.sha256)"
if ($DevelopmentIdentity) {
    Write-Warning 'Development identity only. Do not submit this file to the Store or distribute it as an installable release.'
} else {
    Write-Host 'Partner Center identity supplied; certification and Store publication are still pending.'
}
