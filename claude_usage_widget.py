"""
Claude Usage Widget — 常駐 Windows 桌面的 claude.ai 用量監控小窗（非官方）
https://github.com/aiuser888-bot/claude-usage-widget  ·  MIT License

- 置頂、無邊框、可拖曳的小視窗，每 60 秒自動更新 claude.ai 用量
- sessionKey 存放在 Windows 認證管理員（keyring），不落地成明文檔案
- 左鍵拖曳移動 / 雙擊收合 / 右鍵選單：立即更新、收合展開、透明度、更換 sessionKey、結束
- 錯誤寫入 widget.log（不含 sessionKey）；視窗位置等設定存在 claude_usage_state.json
"""

import json
import logging
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "claude_usage_state.json"
LOG_FILE = HERE / "widget.log"

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, encoding="utf-8",
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("widget")

try:
    import keyring
    from curl_cffi import requests
except Exception as e:  # 缺套件時記錄並顯示
    log.exception("import failed")
    r = tk.Tk(); r.withdraw()
    from tkinter import messagebox
    messagebox.showerror("Claude 用量", f"缺少套件：{e}\n請執行 pip install curl_cffi keyring")
    sys.exit(1)

BASE = "https://claude.ai"
REFRESH_SEC = 60
KR_SERVICE, KR_USER = "ClaudeUsageWidget", "sessionKey"

LABELS = {
    "five_hour": "5 小時額度",
    "seven_day": "每週（全部模型）",
    "seven_day_opus": "每週 Opus",
    "seven_day_sonnet": "每週 Sonnet",
    "seven_day_oauth_apps": "每週 OAuth 應用",
}

BG, FG, DIM, TRACK = "#1c1c1e", "#eeeeee", "#8e8e93", "#3a3a3c"
GREEN, ORANGE, RED = "#30a46c", "#f5a524", "#e5484d"
FONT = ("Microsoft JhengHei UI", 9) if sys.platform == "win32" else ("PingFang TC", 11)
FONT_B = (FONT[0], FONT[1], "bold")


def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(p, obj):
    try:
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def get_key():
    try:
        return keyring.get_password(KR_SERVICE, KR_USER)
    except Exception:
        log.exception("keyring read failed")
        return None


def set_key(k):
    keyring.set_password(KR_SERVICE, KR_USER, k)


def color(p):
    return RED if p >= 90 else ORANGE if p >= 70 else GREEN


def countdown(iso):
    if not iso:
        return ""
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    s = int((t - datetime.now(timezone.utc)).total_seconds())
    if s <= 0:
        return "即將重置"
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return (f"{d}天 " if d else "") + (f"{h}時 " if d or h else "") + f"{m}分後重置"


def on_screen(x, y, sw, sh):
    """左上角附近的點是否落在任一台螢幕上；Windows 用 MonitorFromPoint 判斷，支援負座標的副螢幕。"""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            f = ctypes.windll.user32.MonitorFromPoint
            f.argtypes, f.restype = [wintypes.POINT, wintypes.DWORD], wintypes.HMONITOR
            return bool(f(wintypes.POINT(int(x) + 20, int(y) + 10), 0))  # MONITOR_DEFAULTTONULL
        except Exception:
            pass
    return 0 <= x < sw - 40 and 0 <= y < sh - 40


class AuthError(RuntimeError):
    pass


class UsageClient:
    def __init__(self, session_key):
        self.s = requests.Session(impersonate="chrome")
        self.s.cookies.set("sessionKey", session_key, domain=".claude.ai")
        self.org = None

    def _get(self, path):
        r = self.s.get(BASE + path, timeout=20, headers={"Accept": "application/json"})
        if r.status_code in (401, 403):
            body = r.text[:200].lower()
            if "cloudflare" in body or "just a moment" in body:
                raise RuntimeError(f"被 Cloudflare 擋下（HTTP {r.status_code}）")
            raise AuthError(f"驗證失敗（HTTP {r.status_code}），sessionKey 可能已過期")
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}：{path}")
        try:
            return r.json()
        except Exception:
            raise RuntimeError(f"回應不是 JSON：{path}")

    def usage(self):
        if not self.org:
            orgs = self._get("/api/organizations")
            if not isinstance(orgs, list) or not orgs:
                raise RuntimeError("找不到組織")
            org = next((o for o in orgs if "chat" in (o.get("capabilities") or [])), orgs[0])
            self.org = org["uuid"]
        data = self._get(f"/api/organizations/{self.org}/usage")
        rows = []
        for k, v in (data or {}).items():
            if isinstance(v, dict) and v.get("utilization") is not None:
                u = float(v["utilization"])
                if u <= 1 and u % 1:
                    u *= 100
                rows.append((LABELS.get(k, k), u, v.get("resets_at")))
        if not rows:
            log.warning("usage response had no rows; keys=%s", list((data or {}).keys()))
        return rows


def ask_key(parent=None, msg=""):
    """以遮罩輸入框取得 sessionKey，驗證成功才寫入認證管理員。回傳 key 或 None。"""
    win = tk.Toplevel(parent) if parent else tk.Tk()
    win.title("Claude 用量 - 設定 sessionKey")
    win.attributes("-topmost", True)
    win.configure(bg=BG, padx=16, pady=14)
    win.resizable(False, False)
    tk.Label(win, text=msg or "請貼上 claude.ai 的 sessionKey（會存入 Windows 認證管理員）",
             bg=BG, fg=FG, font=FONT, wraplength=360, justify="left").pack(anchor="w")
    tk.Label(win, text="取得方式：瀏覽器登入 claude.ai → F12 → Application → Cookies → https://claude.ai → sessionKey",
             bg=BG, fg=DIM, font=(FONT[0], FONT[1] - 1), wraplength=360, justify="left").pack(anchor="w", pady=(4, 8))
    var = tk.StringVar()
    ent = tk.Entry(win, textvariable=var, show="•", width=48)
    ent.pack(fill="x")
    status = tk.Label(win, text="", bg=BG, fg="#ff8a8a", font=FONT, wraplength=360, justify="left")
    status.pack(anchor="w", pady=(6, 0))
    result = {"key": None}

    def ok(*_):
        k = var.get().strip().strip('"')
        if not k:
            return
        status.config(text="驗證中…", fg=DIM)
        win.update()
        try:
            UsageClient(k).usage()
        except Exception as e:
            status.config(text=f"驗證失敗：{e}", fg="#ff8a8a")
            log.warning("key validation failed: %s", e)
            return
        try:
            set_key(k)
        except Exception as e:
            status.config(text=f"寫入認證管理員失敗：{e}", fg="#ff8a8a")
            log.exception("keyring write failed")
            return
        log.info("sessionKey saved to Credential Manager")
        result["key"] = k
        win.destroy()

    btns = tk.Frame(win, bg=BG)
    btns.pack(anchor="e", pady=(10, 0))
    tk.Button(btns, text="取消", command=win.destroy, width=8).pack(side="right", padx=(6, 0))
    tk.Button(btns, text="驗證並儲存", command=ok, width=12).pack(side="right")
    ent.bind("<Return>", ok)
    ent.focus_force()
    win.update_idletasks()
    w, h = win.winfo_width(), win.winfo_height()
    win.geometry(f"+{(win.winfo_screenwidth() - w) // 2}+{(win.winfo_screenheight() - h) // 3}")
    if parent:
        win.grab_set()
        parent.wait_window(win)
    else:
        win.mainloop()
    return result["key"]


class Widget:
    def __init__(self, key):
        self.client = UsageClient(key)
        self.rows, self.err, self.last = [], None, None
        self.fetching = False
        st = load_json(STATE_FILE, {})
        self.collapsed = st.get("collapsed", False)
        self.alpha = st.get("alpha", 0.92)

        self.root = tk.Tk()
        self.root.title("Claude 用量")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.alpha)
        self.root.configure(bg=BG)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x, y = st.get("x", sw - 280), st.get("y", sh - 300)
        if not on_screen(x, y, sw, sh):  # 位置不在任何螢幕上時重設（支援多螢幕）
            x, y = sw - 280, sh - 300
        self.root.geometry(f"+{x}+{y}")

        self.frame = tk.Frame(self.root, bg=BG, padx=12, pady=10)
        self.frame.pack(fill="both", expand=True)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="立即更新", command=self.refresh)
        self.menu.add_command(label="收合／展開", command=self.toggle)
        alpha_menu = tk.Menu(self.menu, tearoff=0)
        for a in (1.0, 0.92, 0.8, 0.65, 0.5):
            alpha_menu.add_command(label=f"{int(a * 100)}%", command=lambda a=a: self.set_alpha(a))
        self.menu.add_cascade(label="透明度", menu=alpha_menu)
        self.menu.add_command(label="更換 sessionKey", command=self.change_key)
        self.menu.add_separator()
        self.menu.add_command(label="結束", command=self.quit)

        self._drag = None
        self.root.bind_all("<ButtonPress-1>", self._start_drag)
        self.root.bind_all("<B1-Motion>", self._do_drag)
        self.root.bind_all("<ButtonRelease-1>", self._end_drag)
        self.root.bind_all("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        self.root.bind_all("<Double-Button-1>", lambda e: self.toggle())

        self.render()
        self.refresh()
        self.root.after(30_000, self._tick)
        self.root.after(1000, self._keep_on_top)

    # ---------- 資料 ----------
    def refresh(self):
        if self.fetching:
            return
        self.fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            rows, err = self.client.usage(), None
        except Exception as e:
            rows, err = self.rows, e
        self.root.after(0, self._apply, rows, err)

    def _apply(self, rows, err):
        self.fetching = False
        self.rows = rows
        self.err = str(err) if err else None
        if err:
            log.warning("fetch error: %s", err)
        else:
            self.last = datetime.now()
        self.render()
        if isinstance(err, AuthError):
            self.root.after(200, lambda: self.change_key("sessionKey 已失效，請重新貼上"))

    def _tick(self):
        self.render()
        if not self.last or (datetime.now() - self.last).total_seconds() >= REFRESH_SEC:
            self.refresh()
        self.root.after(30_000, self._tick)

    def _keep_on_top(self):
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
        except Exception:
            pass
        self.root.after(5000, self._keep_on_top)

    # ---------- 畫面 ----------
    def render(self):
        for w in self.frame.winfo_children():
            w.destroy()
        mx = max((r[1] for r in self.rows), default=None)

        head = tk.Frame(self.frame, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="Claude 用量", bg=BG, fg=FG, font=FONT_B).pack(side="left")
        if self.collapsed and mx is not None:
            tk.Label(head, text=f"  {round(mx)}%", bg=BG, fg=color(mx), font=FONT_B).pack(side="left")
        if self.collapsed and self.err:
            tk.Label(head, text="  ⚠", bg=BG, fg="#ff8a8a", font=FONT_B).pack(side="left")

        if not self.collapsed:
            if self.err:
                tk.Label(self.frame, text="⚠ " + self.err, bg=BG, fg="#ff8a8a", font=FONT,
                         wraplength=220, justify="left").pack(anchor="w", pady=(6, 0))
            if not self.rows and not self.err:
                tk.Label(self.frame, text="讀取中…", bg=BG, fg=DIM, font=FONT).pack(anchor="w", pady=(6, 0))
            for label, p, reset in self.rows:
                row = tk.Frame(self.frame, bg=BG)
                row.pack(fill="x", pady=(8, 0))
                tk.Label(row, text=label, bg=BG, fg=FG, font=FONT).pack(side="left")
                tk.Label(row, text=f"{round(p)}%", bg=BG, fg=color(p), font=FONT_B).pack(side="right", padx=(16, 0))
                bar = tk.Canvas(self.frame, width=220, height=6, bg=TRACK, highlightthickness=0)
                bar.pack(fill="x", pady=3)
                bar.create_rectangle(0, 0, int(220 * min(p, 100) / 100), 6, fill=color(p), width=0)
                tk.Label(self.frame, text=countdown(reset), bg=BG, fg=DIM,
                         font=(FONT[0], FONT[1] - 1)).pack(anchor="w")
            if self.last:
                tk.Label(self.frame, text="更新於 " + self.last.strftime("%H:%M:%S"), bg=BG, fg="#5a5a5e",
                         font=(FONT[0], FONT[1] - 2)).pack(anchor="e", pady=(8, 0))
        self.root.update_idletasks()

    # ---------- 互動 ----------
    def change_key(self, msg=""):
        k = ask_key(self.root, msg)
        if k:
            self.client = UsageClient(k)
            self.err = None
            self.refresh()

    def toggle(self):
        self.collapsed = not self.collapsed
        self.render()
        self.save_state()

    def set_alpha(self, a):
        self.alpha = a
        self.root.attributes("-alpha", a)
        self.save_state()

    def _start_drag(self, e):
        if e.widget.winfo_toplevel() is not self.root:
            self._drag = None
            return
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _do_drag(self, e):
        if self._drag:
            self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _end_drag(self, e):
        if self._drag:
            self._drag = None
            self.save_state()

    def save_state(self):
        save_json(STATE_FILE, {"x": self.root.winfo_x(), "y": self.root.winfo_y(),
                               "collapsed": self.collapsed, "alpha": self.alpha})

    def quit(self):
        self.save_state()
        log.info("widget exit")
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def single_instance():
    """避免重複開啟：Windows 用具名 mutex。"""
    if sys.platform != "win32":
        return True
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\ClaudeUsageWidgetMutex")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    if not single_instance():
        log.info("already running, exit")
        return
    log.info("widget start")
    key = get_key()
    if not key:
        key = ask_key()
        if not key:
            log.info("no key provided, exit")
            return
    Widget(key.strip()).run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("fatal")
        raise
