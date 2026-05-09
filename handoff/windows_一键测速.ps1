$ErrorActionPreference = "Stop"

param(
    [Parameter(Mandatory=$true)]
    [string]$HostIp,

    [Parameter(Mandatory=$true)]
    [string]$HealthzUrl
)

Write-Host "注意：旧公网生产入口 OLD_PUBLIC_ENTRY_DISABLED 已完全停用，请显式传入当前服务器地址。" -ForegroundColor Yellow

Write-Host "=== 1) Ping 测试（30次）===" -ForegroundColor Cyan
$pings = Test-Connection -ComputerName $HostIp -Count 30
$loss = [math]::Round((30 - $pings.Count) / 30.0 * 100, 1)
$avg = [math]::Round((($pings | Measure-Object -Property Latency -Average).Average), 1)
$max = [math]::Round((($pings | Measure-Object -Property Latency -Maximum).Maximum), 1)
$min = [math]::Round((($pings | Measure-Object -Property Latency -Minimum).Minimum), 1)
Write-Host ("packet_loss={0}%  rtt_avg={1}ms  rtt_min={2}ms  rtt_max={3}ms" -f $loss, $avg, $min, $max)

Write-Host ""
Write-Host "=== 2) HTTP 健康接口抖动（30次）===" -ForegroundColor Cyan
$times = @()
for ($i = 1; $i -le 30; $i++) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $r = Invoke-WebRequest -Uri $HealthzUrl -UseBasicParsing -TimeoutSec 5
        $sw.Stop()
        $ms = [math]::Round($sw.Elapsed.TotalMilliseconds, 1)
        $times += $ms
        Write-Host ("[{0}] {1} ms" -f $i, $ms)
    } catch {
        $sw.Stop()
        Write-Host ("[{0}] FAIL" -f $i) -ForegroundColor Yellow
    }
    Start-Sleep -Milliseconds 200
}

if ($times.Count -gt 0) {
    $httpAvg = [math]::Round((($times | Measure-Object -Average).Average), 1)
    $httpMax = [math]::Round((($times | Measure-Object -Maximum).Maximum), 1)
    $httpMin = [math]::Round((($times | Measure-Object -Minimum).Minimum), 1)
    $httpJitter = [math]::Round($httpMax - $httpMin, 1)
    Write-Host ("http_ok={0}/30  avg={1}ms  min={2}ms  max={3}ms  jitter={4}ms" -f $times.Count, $httpAvg, $httpMin, $httpMax, $httpJitter)
} else {
    Write-Host "http_ok=0/30" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== 3) 快速结论 ===" -ForegroundColor Cyan
$scoreBad = $false
$scoreWarn = $false

if ($loss -gt 0) { $scoreWarn = $true }
if ($avg -gt 260) { $scoreWarn = $true }
if ($max -gt 600) { $scoreBad = $true }

if ($times.Count -lt 24) { $scoreBad = $true }
elseif ($times.Count -lt 30) { $scoreWarn = $true }

if ($times.Count -gt 0) {
    if ($httpJitter -gt 800) { $scoreBad = $true }
    elseif ($httpJitter -gt 300) { $scoreWarn = $true }
    if ($httpAvg -gt 500) { $scoreBad = $true }
    elseif ($httpAvg -gt 250) { $scoreWarn = $true }
}

if ($scoreBad) {
    Write-Host "网络结论：较差（很可能导致语音卡顿/断续）" -ForegroundColor Red
} elseif ($scoreWarn) {
    Write-Host "网络结论：一般（有卡顿风险，建议换网络再测）" -ForegroundColor Yellow
} else {
    Write-Host "网络结论：正常（网络大概率不是主因）" -ForegroundColor Green
}

Write-Host ""
Write-Host "请把整段输出截图发回。"
