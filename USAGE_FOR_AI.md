# Claude 用量紀錄：給其他對話（AI）的使用說明

用途：在執行排程或任務**前後**各記一次 claude.ai 用量，算出這次任務消耗了多少額度。
資料來源是常駐在使用者 Windows 電腦上的「Claude 用量小窗」，它每 60 秒自動記錄一次，也可以被要求立即更新。

## 1. 前提

- 這個對話必須連到使用者的電腦，而且已連接 `C:\Users\AI\Desktop\ClaudeWork` 資料夾。
- 在 `device_bash`（電腦上的 Linux shell）裡，程式資料夾路徑是：
  `$HOME/mnt/ClaudeWork/ClaudeUsageWidget`
- 用 `python3` 執行（只用標準函式庫，免安裝）。
- 小窗必須在執行中，`mark`／`snapshot` 才能拿到即時數字（開機會自動啟動）。

## 2. 量測一個任務的用量（標準流程）

```bash
cd "$HOME/mnt/ClaudeWork/ClaudeUsageWidget"
python3 usage_query.py mark "<任務名>-<YYYYMMDD-HHMM> start"
#  ……執行任務……
python3 usage_query.py mark "<任務名>-<YYYYMMDD-HHMM> end"
python3 usage_query.py diff "mark:<任務名>-<YYYYMMDD-HHMM> start" "mark:<任務名>-<YYYYMMDD-HHMM> end"
```

- 標籤名稱要**唯一**（建議加日期時間），`mark:LABEL` 會取同名標籤中最新的一個。
- `mark` 會要求小窗立即更新並等新數字寫入（通常 1～2 秒，最多 30 秒），所以前後兩點都是即時值。

## 3. 指令一覽（輸出皆為 JSON）

| 指令 | 用途 |
|---|---|
| `latest` | 最新一筆紀錄，附 `age_seconds`（距今秒數） |
| `snapshot` | 要求立即更新，輸出新寫入的那一筆 |
| `mark LABEL` | 立即更新並記下標記（寫入 `usage_history/marks.jsonl`） |
| `diff FROM TO [--metric five_hour]` | 兩個時間點之間的消耗 |
| `at TIME` | 某時間點當下（或之前最近）的一筆 |
| `range FROM TO` | 區間內所有紀錄 |
| `marks --last N` | 最近 N 個標記 |

FROM／TO／TIME 可寫：`mark:LABEL`、`now`、`now-30m`／`now-2h`／`now-1d`、ISO 時間（如 `"2026-11-07 09:00"`，未寫時區即視為台灣時間 +08:00）。

## 4. 輸出怎麼讀

`diff` 範例：
```json
{"ok": true, "from_record_t": "...", "to_record_t": "...", "records": 12,
 "consumption": {
   "five_hour": {"used_pct_points": 7.0, "resets_in_between": 0, "from_pct": 41.0, "to_pct": 48.0},
   "seven_day": {"used_pct_points": 1.0, "resets_in_between": 0, "from_pct": 13.0, "to_pct": 14.0}}}
```
- `five_hour`：5 小時額度；`seven_day`：每週額度（全部模型）。帳號有提供時還會出現 `seven_day_opus` 等分項。
- `used_pct_points`：消耗了幾個**百分點**（不是 token 數）。
- `resets_in_between` > 0：期間額度重置過；消耗已含重置後的用量，但重置前最後一分鐘內的用量可能漏算。

`mark` 輸出裡：
- `"fresh": true`：即時數字，可信。
- `"fresh": false` 並附 `warning`：小窗沒回應或抓取失敗，改用最後一筆成功紀錄，回報時要註明。

## 5. 必須注意

- **解析度 1 個百分點**：短任務常量到 0，請回報「<1 個百分點」，不要寫成「沒有消耗」。
- **同時間的其他使用也會算進去**：使用者在其他對話或 Claude Code 的用量共用同一額度，區間內的消耗不全然屬於這個任務。
- 抓取失敗的紀錄是 `"ok": false`，`diff`／`at` 會自動略過。
- **不要修改或刪除** `usage_history/` 裡的檔案（小窗自己管理，總量超過 500 MB 時自動刪最舊的日檔）。
- 輸出盡量精簡以節省用量，例如只取需要的欄位：
  ```bash
  python3 usage_query.py diff "mark:A start" "mark:A end" | python3 -c "import json,sys;d=json.load(sys.stdin);print({k:v['used_pct_points'] for k,v in d['consumption'].items()})"
  ```

## 6. 出問題時

| 狀況 | 處理 |
|---|---|
| `no new record within 30s` | 小窗沒在執行。請使用者雙擊桌面「啟動用量小窗」 |
| `latest` 的 `age_seconds` 遠大於 60 | 同上，或電腦剛從睡眠喚醒 |
| 紀錄裡的 `error` 出現「驗證失敗」 | sessionKey 過期，請使用者在小窗右鍵 →「更換 sessionKey」 |
| 找不到 `$HOME/mnt/ClaudeWork` | 這個對話沒有連接 ClaudeWork 資料夾，請使用者加入 |

原始碼與說明：https://github.com/aiuser888-bot/claude-usage-widget
