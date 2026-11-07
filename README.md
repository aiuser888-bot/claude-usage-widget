# Claude Usage Widget

一個常駐在 Windows 桌面的小視窗，即時顯示 claude.ai 訂閱方案（Pro / Max / Team）的用量百分比與重置倒數，不用再一直點進設定頁查看。

A tiny always-on-top Windows desktop widget that shows your claude.ai plan usage (5-hour and weekly limits) with reset countdowns. English summary [below](#english).

> ⚠️ **非官方專案**：本專案與 Anthropic 無任何關係，也未獲其背書。它使用 claude.ai 網頁本身的內部 API（`/api/organizations/{org}/usage`），並非公開文件化的介面，Anthropic 改版時隨時可能失效。

## 功能

- 置頂、無邊框、半透明的小視窗，每 60 秒自動更新
- 顯示 5 小時額度、每週額度（帳號有提供時也會顯示 Opus / Sonnet 分項），附進度條與重置倒數
- 顏色提示：< 70% 綠、70–90% 橘、≥ 90% 紅
- **sessionKey 存在 Windows 認證管理員**（透過 `keyring`），不會以明文寫入任何檔案
- 首次啟動跳出遮罩輸入框，先實際驗證成功才儲存；sessionKey 失效時自動要求重新輸入
- 支援多螢幕，記住視窗位置、收合狀態、透明度
- 防止重複開啟（Windows 具名 mutex）
- 錯誤記錄在 `widget.log`（不含 sessionKey）
- 每次更新寫入用量紀錄檔，附查詢工具 `usage_query.py`，可量測排程前後的用量消耗

## 用量紀錄（給排程或其他程式使用）

小窗每次更新（預設每 60 秒）都會把時間與用量寫進 `usage_history/usage_YYYY-MM-DD.jsonl`，一行一筆：

```json
{"t":"2026-11-07T09:30:00+08:00","ok":true,"src":"timer","usage":{"five_hour":{"pct":41.0,"resets_at":"..."},"seven_day":{"pct":13.0,"resets_at":"..."}},"error":null}
```

- 總量上限 500 MB，超過時自動刪除最舊的日檔（以每天約 1,440 筆估算，可保存數年）
- 抓取失敗也會記一筆 `"ok": false`，方便判斷資料缺口
- `src`：`timer`（定時）、`request`（外部要求）、`start`、`manual`

### `usage_query.py`：查詢與量測排程前後的消耗

只用 Python 標準函式庫，輸出 JSON。

```bash
python usage_query.py latest                      # 最新一筆
python usage_query.py snapshot                    # 要求小窗立即更新，等新紀錄寫入後輸出
python usage_query.py mark "job-A start"          # 立即更新並記下標記
# ...執行排程...
python usage_query.py mark "job-A end"
python usage_query.py diff "mark:job-A start" "mark:job-A end"   # 兩點之間的消耗
python usage_query.py diff now-2h now --metric five_hour
python usage_query.py at "2026-11-07 09:00"
python usage_query.py range now-30m now
python usage_query.py marks --last 10
```

`diff` 會把各區段的百分比上升量加總；中途遇到額度重置（百分比下降）時，以重置後的百分比計入並回報 `resets_in_between`。API 提供的是整數百分比，解析度為 1 個百分點。

`snapshot` / `mark` 透過在程式資料夾建立 `.refresh_request` 檔通知小窗，小窗每秒檢查一次，所以小窗必須在執行中。

## 操作

| 動作 | 效果 |
|---|---|
| 左鍵拖曳 | 移動位置 |
| 雙擊 | 收合成一行（只顯示最高百分比） |
| 右鍵 | 立即更新／收合展開／透明度／更換 sessionKey／結束 |

## 安裝（Windows 10 / 11）

1. 下載或 clone 本專案到一個固定的資料夾（之後不要搬動，捷徑會指向這裡）
2. 雙擊 `install.bat`
   - 找不到 Python 時會用 `winget` 安裝 Python 3.12（使用者層級，不需系統管理員）
   - 安裝 `curl_cffi`、`keyring`
   - 建立「開機自動啟動」與「桌面」捷徑，並啟動小窗
3. 在跳出的視窗貼上 sessionKey，按「驗證並儲存」

### 取得 sessionKey

在瀏覽器登入 claude.ai → 按 `F12` → **Application** → **Cookies** → `https://claude.ai` → 複製 `sessionKey` 的值。

> 🔐 **sessionKey 等同你帳號的完整登入憑證**，請勿分享、勿提交到任何 repo。官方目前沒有「只能讀取用量」的權杖。若懷疑外洩，到 claude.ai 登出所有裝置即可讓它失效。
>
> 小建議：在無痕視窗登入 claude.ai 取出 sessionKey 後**直接關閉視窗、不要按登出**，這組 key 就只供小工具使用，與你平常的登入工作階段分開。

### 手動安裝（不用腳本）

```powershell
pip install -r requirements.txt
pythonw claude_usage_widget.py
```

## 移除

雙擊 `uninstall.bat`：結束小窗、刪除兩個捷徑、從認證管理員移除 sessionKey、刪除狀態與紀錄檔。不會解除安裝 Python。

## 檔案說明

| 檔案 | 用途 |
|---|---|
| `claude_usage_widget.py` | 主程式 |
| `install.bat` / `install.ps1` | 安裝腳本 |
| `uninstall.bat` / `uninstall.ps1` | 移除腳本 |
| `requirements.txt` | Python 相依套件 |
| `usage_query.py` | 用量紀錄查詢工具 |
| `USAGE_FOR_AI.md` | 給其他 AI 對話的查詢工具使用說明 |
| `claude_usage_state.json` | （執行時產生）視窗位置等設定 |
| `usage_history/` | （執行時產生）用量紀錄與標記 |
| `widget.log` | （執行時產生）啟動與錯誤紀錄 |

## 疑難排解

- **顯示「驗證失敗」**：sessionKey 過期或已登出，右鍵 →「更換 sessionKey」重新貼上。
- **顯示「被 Cloudflare 擋下」**：通常是暫時性的，稍後自動重試；持續發生請更新 `curl_cffi`。
- **小窗不見了**（例如按了 Win+D「顯示桌面」或螢幕配置改變）：再點一次桌面捷徑即可，執行中的小窗會在 5 秒內自動回到主螢幕右下角；小窗每 5 秒也會自行檢查並拉回畫面內。仍無效再查看 `widget.log`。
- **API 格式改變導致無資料**：`widget.log` 會記錄回應的欄位名稱，歡迎開 issue。

## 隱私

小工具只會連線到 `claude.ai`，使用你自己的 sessionKey 讀取你自己的用量，不會傳送任何資料到其他地方。

---

## English

An unofficial, always-on-top desktop widget for Windows that displays your claude.ai subscription usage (5-hour window, weekly limits, and per-model weekly limits when available) with progress bars and reset countdowns, refreshing every 60 seconds.

- **Not affiliated with or endorsed by Anthropic.** It relies on claude.ai's internal web API, which is undocumented and may change at any time.
- Your `sessionKey` cookie is stored in **Windows Credential Manager** via `keyring`, never in plain text. It is validated before saving, and you are re-prompted automatically when it expires.
- **Install:** clone to a permanent folder, run `install.bat`, then paste your `sessionKey` (DevTools → Application → Cookies → `https://claude.ai`).
- **Uninstall:** run `uninstall.bat`.
- **Controls:** drag to move, double-click to collapse, right-click for refresh / opacity / change key / exit.

> The `sessionKey` is a full-access login credential for your account. Never share it or commit it anywhere.

## License

[MIT](LICENSE)
