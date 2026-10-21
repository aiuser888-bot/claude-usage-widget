# Claude Usage Widget 安裝腳本（Windows）
# 1. 找不到 Python 時用 winget 安裝 Python 3.12（使用者層級）
# 2. 安裝 curl_cffi、keyring
# 3. 建立開機自動啟動捷徑與桌面捷徑
# 4. 啟動小窗（首次啟動會要求貼上 sessionKey，存入 Windows 認證管理員）
$ErrorActionPreference = 'Continue'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logf = Join-Path $dir 'setup.log'
Set-Content -Path $logf -Value "=== install $(Get-Date -Format s) ===" -Encoding UTF8
function L($m) { Write-Host $m; Add-Content -Path $logf -Value $m -Encoding UTF8 }

function Find-Python {
    foreach ($c in @('py', 'python')) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if (-not $cmd -or $cmd.Source -like '*WindowsApps*') { continue }   # 略過 Microsoft Store 假捷徑
        $a = if ($c -eq 'py') { @('-3', '-c') } else { @('-c') }
        $exe = & $c @a 'import sys;print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
    }
    foreach ($p in Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "C:\Program Files\Python3*\python.exe" -ErrorAction SilentlyContinue) { return $p.FullName }
    return $null
}

$py = Find-Python
if (-not $py) {
    L '找不到 Python，使用 winget 安裝 Python 3.12…'
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $py = Find-Python
}
if (-not $py) { L 'ERROR: Python 安裝失敗，請手動安裝 Python 3.9 以上版本後再執行。'; exit 1 }
L "Python: $py ($(& $py --version 2>&1))"

L '安裝相依套件 curl_cffi、keyring…'
& $py -m pip install --upgrade --disable-pip-version-check -r (Join-Path $dir 'requirements.txt')
$chk = & $py -c "import curl_cffi, keyring, tkinter; print('OK', curl_cffi.__version__, keyring.get_keyring().__class__.__name__)" 2>&1
L "套件檢查: $chk"
if ($chk -notlike 'OK*') { L 'ERROR: 套件安裝或匯入失敗'; exit 1 }

$pyw = Join-Path (Split-Path $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }
$script = Join-Path $dir 'claude_usage_widget.py'
$ws = New-Object -ComObject WScript.Shell

function New-Shortcut($path) {
    $s = $ws.CreateShortcut($path)
    $s.TargetPath = $pyw; $s.Arguments = "`"$script`""; $s.WorkingDirectory = $dir
    $s.IconLocation = "$pyw,0"; $s.Description = 'Claude Usage Widget'; $s.Save()
    L "捷徑: $path"
}
New-Shortcut (Join-Path ([Environment]::GetFolderPath('Startup')) 'Claude Usage Widget.lnk')
New-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Claude Usage Widget.lnk')

Start-Process -FilePath $pyw -ArgumentList "`"$script`"" -WorkingDirectory $dir
L '已啟動小窗。首次執行請在彈出視窗貼上 sessionKey。'
L 'DONE'
