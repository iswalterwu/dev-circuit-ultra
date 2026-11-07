<#
.SYNOPSIS
  在项目之外创建一个私有 dev-circuit-ultra 账本仓库。

.DESCRIPTION
  真正的实现是 devcircuit CLI 的 ledger 子命令；这个脚本只负责转发参数。
  等价命令：

    devcircuit ledger --path <项目之外的目录> [--no-commit]

.EXAMPLE
  pwsh -NoProfile -File new-ledger.ps1 -Path D:\ledgers\my-app
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Path,
  [switch]$NoCommit
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)

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
  $env:PYTHONPATH = if ($env:PYTHONPATH) { "$tools;$env:PYTHONPATH" } else { $tools }
  $exe = 'python'
  $prefix = @('-m', 'devcircuit.cli')
}

$call = @($prefix) + @('ledger', '--path', $Path)
if ($NoCommit) { $call += '--no-commit' }

& $exe @call
exit $LASTEXITCODE
