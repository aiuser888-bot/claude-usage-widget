# Claude Usage Widget 移除腳本（Windows）
# 結束小窗、刪除捷徑、從 Windows 認證管理員移除 sessionKey。不會解除安裝 Python 與套件。
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $dir 'claude_usage_widget.py'

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*claude_usage_widget.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "已結束 PID $($_.ProcessId)" }

foreach ($f in @([Environment]::GetFolderPath('Startup'), [Environment]::GetFolderPath('Desktop'))) {
    $lnk = Join-Path $f 'Claude Usage Widget.lnk'
    if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "已刪除 $lnk" }
}

cmdkey /delete:ClaudeUsageWidget | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host '已從認證管理員移除 sessionKey' } else { Write-Host '認證管理員中沒有 ClaudeUsageWidget 項目' }

foreach ($f in @('claude_usage_state.json', 'widget.log', 'setup.log')) {
    $p = Join-Path $dir $f
    if (Test-Path $p) { Remove-Item $p -Force }
}
Write-Host '移除完成。'
