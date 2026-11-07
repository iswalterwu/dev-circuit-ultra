<#
.SYNOPSIS
  把三个技能同步到 Claude Code / agents / DeepSeek Harness 的技能目录。

.DESCRIPTION
  真正的实现是 devcircuit CLI 的 sync 子命令；这个脚本只负责转发参数。
  等价命令：

    devcircuit sync [--target <目录>]...

.EXAMPLE
  pwsh -NoProfile -File sync.ps1

.EXAMPLE
  pwsh -NoProfile -File sync.ps1 -Target ~/.pi/skills
#>
[CmdletBinding()]
param(
  [string[]]$Target
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)

$command = Get-Command devcircuit -CommandType Application -ErrorAction SilentlyContinue
$prefix = @()
if ($command) {
  $exe = $command.Source
} else {
  $tools = Join-Path $PSScriptRoot 'tools'
  if (-not (Test-Path -LiteralPath (Join-Path $tools 'devcircuit'))) {
    throw '找不到 devcircuit。先安装：pipx install git+https://github.com/iswalterwu/dev-circuit-ultra'
  }
  $env:PYTHONPATH = if ($env:PYTHONPATH) { "$tools;$env:PYTHONPATH" } else { $tools }
  $exe = 'python'
  $prefix = @('-m', 'devcircuit.cli')
}

$call = @($prefix) + @('sync')
foreach ($item in $Target) { $call += @('--target', $item) }

& $exe @call
exit $LASTEXITCODE
