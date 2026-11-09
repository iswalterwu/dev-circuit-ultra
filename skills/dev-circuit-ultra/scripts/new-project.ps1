<#
.SYNOPSIS
  新建 dev-circuit-ultra 项目骨架，或给已有的 Git 仓库补齐需要的文件。

.DESCRIPTION
  真正的实现是 devcircuit CLI 的 init 子命令；这个脚本只负责转发参数，
  所以在任何平台上的行为都一致。等价命令：

    devcircuit init --path <目录> [--name <项目名>] [--adopt]

.EXAMPLE
  pwsh -NoProfile -File new-project.ps1 -Path D:\code\my-app -Name "My App"

.EXAMPLE
  pwsh -NoProfile -File new-project.ps1 -Path D:\code\existing-repo -Adopt
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Path,
  [string]$Name,
  [switch]$Adopt
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)

# 1) 已安装的 CLI；2) 仓库 checkout（这个脚本在 <repo>/skills/dev-circuit-ultra/scripts）
$command = Get-Command devcircuit -CommandType Application -ErrorAction SilentlyContinue
$prefix = @()
if ($command) {
  $exe = $command.Source
} else {
  $repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
  $tools = Join-Path $repo 'tools'
  if (-not (Test-Path -LiteralPath (Join-Path $tools 'devcircuit'))) {
    throw '找不到 devcircuit。先安装：pipx install git+https://github.com/iswalterwu/dev-circuit-ultra'
  }
  $env:PYTHONPATH = if ($env:PYTHONPATH) { "$tools$([IO.Path]::PathSeparator)$env:PYTHONPATH" } else { $tools }
  $exe = 'python'
  $prefix = @('-m', 'devcircuit.cli')
}

$call = @($prefix) + @('init', '--path', $Path)
if ($Name) { $call += @('--name', $Name) }
if ($Adopt) { $call += '--adopt' }

& $exe @call
exit $LASTEXITCODE
