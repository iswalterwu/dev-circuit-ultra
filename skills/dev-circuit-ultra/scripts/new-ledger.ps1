<#
.SYNOPSIS
  在项目之外创建一个私有 dev-circuit-ultra 账本仓库。

.DESCRIPTION
  账本只给 human 和 dev-circuit-archivist 使用；开发 agent 不读、不写，也不挂载。
  脚本从 skills/dev-circuit-ultra/templates/ledger 复制模板，git init，并做第一次提交。
  目标目录必须不存在或为空，且应当位于项目目录之外。

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

$skillRoot = Split-Path -Parent $PSScriptRoot
$template = Join-Path $skillRoot 'templates/ledger'
if (-not (Test-Path -LiteralPath $template -PathType Container)) {
  throw "Ledger template not found: $template"
}

if (Test-Path -LiteralPath $Path) {
  if (@(Get-ChildItem -LiteralPath $Path -Force).Count -gt 0) {
    throw "目标目录不是空的：$Path"
  }
} else {
  New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

$root = (Resolve-Path -LiteralPath $Path).Path
Get-ChildItem -LiteralPath $template -Force | Copy-Item -Destination $root -Recurse -Force
New-Item -ItemType Directory -Path (Join-Path $root 'entries') -Force | Out-Null

& git -C $root init -q -b main
if ($LASTEXITCODE -ne 0) { throw 'git init 失败' }
& git -C $root add -A
if ($LASTEXITCODE -ne 0) { throw 'git add 失败' }

if (-not $NoCommit) {
  & git -C $root commit -q -m 'chore: initialize dev-circuit-ultra ledger' -m '为什么：把决策历史放在项目外，只供 human 回溯。'
  if ($LASTEXITCODE -ne 0) { throw 'git commit 失败；请先配置 git user.name / user.email，或使用 -NoCommit' }
}

Write-Host "账本：$root"
Write-Host '这是私有仓库：请添加私有 remote，不要把开发容器挂载到这里。'
Write-Host '下一步：在 dev-circuit-archivist 容器里用 /ledger 挂载它；开发容器不要挂载。'
