# Update the local executable from the most recent successful main-branch GitHub Actions build.
$ErrorActionPreference = 'Stop'
$repo = 'Skylark51/ForPublish'
$projectDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$target = Join-Path $projectDir 'ForPublish.exe'
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'GitHub CLI(gh)가 없습니다. winget install --id GitHub.cli -e 로 설치하세요.'
}
$running = Get-Process ForPublish -ErrorAction SilentlyContinue
if ($running) {
    throw '실행 중인 ForPublish.exe를 종료한 뒤 다시 실행하세요.'
}
$runId = gh run list --repo $repo --workflow windows-build.yml --branch main --status success --limit 1 --json databaseId --jq '.[0].databaseId'
if ($LASTEXITCODE -ne 0 -or -not $runId) { throw '성공한 main Windows 빌드를 찾지 못했습니다.' }
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $temp | Out-Null
try {
    gh run download $runId --repo $repo --name ForPublish-Windows --dir $temp
    if ($LASTEXITCODE -ne 0) { throw 'GitHub Actions 빌드 다운로드 실패' }
    $source = Join-Path $temp 'ForPublish.exe'
    if (-not (Test-Path $source)) { throw '다운로드에서 ForPublish.exe를 찾지 못했습니다.' }
    if (Test-Path $target) {
        $backupDir = Join-Path $projectDir 'backups'
        New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        Copy-Item $target (Join-Path $backupDir "ForPublish-$stamp.exe")
    }
    Copy-Item $source $target -Force
    Write-Host "ForPublish 업데이트 완료: $target (Actions run $runId)"
} finally {
    Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
}
