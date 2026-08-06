# GCA news monitor - backup trigger for GitHub Actions
# GitHub cron often misses slots; this fires workflow_dispatch every 30 min
# while the PC is on during business hours (08-18 KST).
# Remove with:  schtasks /Delete /TN "GCA-News-Trigger" /F

$ErrorActionPreference = 'SilentlyContinue'
$repo = 'kwannnnnnnnnn/gca-daily-news'
$log  = Join-Path $PSScriptRoot '_trigger.log'

function Log($m) { "$(Get-Date -Format 'MM-dd HH:mm') $m" | Add-Content -Path $log -Encoding UTF8 }

$h = (Get-Date).Hour
if ($h -lt 8 -or $h -ge 18) { exit 0 }

$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) { Log 'SKIP no gh'; exit 0 }

$last = & $gh run list -R $repo -L 1 --json createdAt -q '.[0].createdAt' 2>$null
if ($last) {
    try {
        $t0 = ([datetime]::Parse($last)).ToUniversalTime()
        $age = (New-TimeSpan -Start $t0 -End (Get-Date).ToUniversalTime()).TotalMinutes
        if ($age -lt 25) { Log ("SKIP recent run {0:N0} min ago" -f $age); exit 0 }
    } catch { }
}

& $gh workflow run daily.yml -R $repo 2>$null
if ($LASTEXITCODE -eq 0) { Log 'RUN triggered' } else { Log "FAIL exit=$LASTEXITCODE" }

if ((Test-Path $log) -and ((Get-Item $log).Length -gt 100KB)) {
    Get-Content $log -Tail 200 | Set-Content $log -Encoding UTF8
}
