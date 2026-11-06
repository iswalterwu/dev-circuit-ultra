<#
.SYNOPSIS
  用 dev-circuit-ultra 骨架新建项目，或给已有的 Git 仓库补上 dev-circuit-ultra 需要的文件。

.DESCRIPTION
  新建模式：目标目录必须不存在或为空。脚本生成 AGENTS.md、CLAUDE.md、specs/backlog.md、
  docs/README.md、docs/requirements/README.md、scripts/doc_guard.py、scripts/spec_check.py、
  .githooks/pre-commit、doc-guard CI 和 .gitattributes，
  然后执行 git init、设置 hooksPath，并做第一次提交。

  接入模式（-Adopt）：目标必须是已有的 Git 仓库。只补缺失的文件，已有文件一律不覆盖，也不提交。
  .gitattributes 已存在时只追加 hook 的换行规则。最后运行 doc_guard 和 spec_check，报出检查结果。

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
$skillRoot = Split-Path -Parent $PSScriptRoot
$templates = Join-Path $skillRoot 'templates'
$skeleton = Join-Path $templates 'project'
$utf8 = [Text.UTF8Encoding]::new($false)
$hookRule = '.githooks/** text eol=lf'

function Read-Text([string]$file) {
  ([IO.File]::ReadAllText($file, $utf8)) -replace "`r`n", "`n"
}

function Invoke-Git {
  & git -C $root @args
  if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') 失败（退出码 $LASTEXITCODE）" }
}

if ($Adopt) {
  if (-not (Test-Path -LiteralPath (Join-Path $Path '.git'))) {
    throw "-Adopt 需要一个已有的 Git 仓库：$Path"
  }
} elseif (Test-Path -LiteralPath $Path) {
  if (@(Get-ChildItem -LiteralPath $Path -Force).Count -gt 0) {
    throw "目标目录不是空的：$Path。接入已有项目请加 -Adopt。"
  }
} else {
  New-Item -ItemType Directory -Path $Path | Out-Null
}

$root = (Resolve-Path -LiteralPath $Path).Path
if (-not $Name) { $Name = Split-Path -Leaf $root }

$created = [Collections.Generic.List[string]]::new()
$skipped = [Collections.Generic.List[string]]::new()

function Write-ProjectFile([string]$relative, [string]$content) {
  $target = Join-Path $root $relative
  if (Test-Path -LiteralPath $target) {
    $skipped.Add($relative)
    return
  }
  $directory = Split-Path -Parent $target
  if (-not (Test-Path -LiteralPath $directory)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
  }
  [IO.File]::WriteAllText($target, $content, $utf8)
  $created.Add($relative)
}

Write-ProjectFile 'AGENTS.md' ((Read-Text (Join-Path $templates 'AGENTS.md')).Replace('<项目名>', $Name))
Write-ProjectFile 'CLAUDE.md' (Read-Text (Join-Path $skeleton 'CLAUDE.md'))
Write-ProjectFile 'specs/backlog.md' (Read-Text (Join-Path $templates 'backlog.md'))
Write-ProjectFile 'docs/README.md' (Read-Text (Join-Path $skeleton 'docs/README.md'))
Write-ProjectFile 'scripts/doc_guard.py' (Read-Text (Join-Path $PSScriptRoot 'doc_guard.py'))
Write-ProjectFile 'scripts/spec_check.py' (Read-Text (Join-Path $PSScriptRoot 'spec_check.py'))
Write-ProjectFile 'docs/requirements/README.md' (Read-Text (Join-Path $skeleton 'docs/requirements/README.md'))
Write-ProjectFile '.githooks/pre-commit' (Read-Text (Join-Path $skeleton '.githooks/pre-commit'))
Write-ProjectFile '.github/workflows/doc-guard.yml' (Read-Text (Join-Path $skeleton '.github/workflows/doc-guard.yml'))

$attributes = Join-Path $root '.gitattributes'
if (-not (Test-Path -LiteralPath $attributes)) {
  $lines = if ($Adopt) { @($hookRule) } else { @('* text=auto eol=lf', $hookRule) }
  [IO.File]::WriteAllText($attributes, (($lines -join "`n") + "`n"), $utf8)
  $created.Add('.gitattributes')
} elseif (-not ((Read-Text $attributes) -split "`n" | Where-Object { $_.Trim() -eq $hookRule })) {
  $existing = Read-Text $attributes
  if ($existing.Length -gt 0 -and -not $existing.EndsWith("`n")) { $existing += "`n" }
  [IO.File]::WriteAllText($attributes, $existing + $hookRule + "`n", $utf8)
  $created.Add('.gitattributes（追加了 hook 换行规则）')
} else {
  $skipped.Add('.gitattributes')
}

if (-not $Adopt) { Invoke-Git init -q -b main }
Invoke-Git config core.hooksPath .githooks

& python (Join-Path $root 'scripts/doc_guard.py') --root $root
$guardExit = $LASTEXITCODE
& python (Join-Path $root 'scripts/spec_check.py') --root $root
$specExit = $LASTEXITCODE

if (-not $Adopt) {
  if ($guardExit -ne 0) { throw '新项目骨架没有通过 doc_guard，请检查模板。' }
  if ($specExit -ne 0) { throw '新项目骨架没有通过 spec_check，请检查模板。' }
  Invoke-Git add -A
  Invoke-Git update-index --chmod=+x .githooks/pre-commit
  Invoke-Git commit -q -m 'chore: 初始化 dev-circuit-ultra 项目骨架' -m '为什么：从第一天起使用 dev-circuit-ultra 的短入口、设计澄清和防回流检查。'
}

Write-Host "项目：$root"
Write-Host ('新建：' + $(if ($created.Count) { $created -join '、' } else { '无' }))
Write-Host ('已存在、未覆盖：' + $(if ($skipped.Count) { $skipped -join '、' } else { '无' }))
Write-Host "doc_guard 退出码：$guardExit"
Write-Host "spec_check 退出码：$specExit"
if ($Adopt) {
  Write-Host '下一步：填写 AGENTS.md 里的项目事实；按上面 doc_guard 报出的问题清理旧文档；然后 git add -A，运行 git update-index --chmod=+x .githooks/pre-commit，再提交。'
} else {
  Write-Host '下一步：填写 AGENTS.md 里的项目事实（命令、代码地图、红线），然后开始设计澄清，写第一张卡。'
}
