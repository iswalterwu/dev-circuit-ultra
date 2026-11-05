[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'
$sourceRoot = Join-Path $PSScriptRoot 'skills'
if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
  throw "Skill source directory not found: $sourceRoot"
}

$gitPath = $PSScriptRoot.Replace('\', '/')
$version = & git -c "safe.directory=$gitPath" -C $PSScriptRoot rev-parse --short HEAD
if ($LASTEXITCODE -ne 0 -or -not $version) {
  throw "Could not read spec-loop Git version from $PSScriptRoot"
}

$skills = @(Get-ChildItem -LiteralPath $sourceRoot -Directory | Sort-Object Name)
$targets = @(
  (Join-Path $env:USERPROFILE '.claude\skills')
  (Join-Path $env:USERPROFILE '.agents\skills')
)

foreach ($target in $targets) {
  if (-not (Test-Path -LiteralPath $target -PathType Container)) {
    if ($PSCmdlet.ShouldProcess($target, 'Create skill directory')) {
      New-Item -ItemType Directory -Path $target -Force | Out-Null
    }
  }

  foreach ($skill in $skills) {
    $destination = Join-Path $target $skill.Name
    $canCopy = $true
    if (Test-Path -LiteralPath $destination) {
      if ($PSCmdlet.ShouldProcess($destination, "Remove existing skill '$($skill.Name)'")) {
        Remove-Item -LiteralPath $destination -Recurse -Force
      } else {
        $canCopy = $false
      }
    }
    if ($canCopy -and $PSCmdlet.ShouldProcess($destination, "Copy skill '$($skill.Name)'")) {
      Copy-Item -LiteralPath $skill.FullName -Destination $destination -Recurse -Force
    }
  }

  Write-Host ('{0}: {1} skills synced (spec-loop {2})' -f $target, $skills.Count, $version)
}
