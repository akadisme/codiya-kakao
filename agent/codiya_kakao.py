# -*- coding: utf-8 -*-
"""
코디야 카톡발송 (PC 프로그램)
 · 코디야 아이디로 로그인 → 화면 오른쪽 아래 아이콘으로 상주
 · 1분마다 코디야 서버에 "지금 보낼 거 있어?" → 서버가 준 것만 카카오톡으로 보냄 → 결과 보고
 · 보낼지 말지(이용기간 · 방 한도 · 같은 방 간격·횟수)는 전부 서버가 정해요
"""
import ctypes
import datetime
import json
import logging
import os
import queue
import random
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

import win32api
import win32event
import winerror

import kakao_core as kc

APP_NAME = "코디야 카톡발송"
VERSION = "1.0.0"
API = "https://codiya.kr/appapi/kakao_pc.php"
HOME = "https://codiya.kr/my/kakao.php"
VER_URL = "https://api.codiya.kr/pc/kakao_version.json"
TASK_NAME = "CodiyaKakao"

DATA = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "CodiyaKakao")
os.makedirs(os.path.join(DATA, "logs"), exist_ok=True)
os.makedirs(os.path.join(DATA, "img"), exist_ok=True)
log = logging.getLogger("codiya_kakao")


# ---------------------------------------------------------------- 공통
def setup_logging():
    fn = os.path.join(DATA, "logs", datetime.date.today().strftime("%Y-%m-%d") + ".log")
    h = logging.FileHandler(fn, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    # 30일 지난 기록은 지움
    try:
        cut = time.time() - 30 * 86400
        for f in os.listdir(os.path.join(DATA, "logs")):
            p = os.path.join(DATA, "logs", f)
            if os.path.getmtime(p) < cut:
                os.remove(p)
    except Exception:
        pass


class Settings:
    path = os.path.join(DATA, "settings.json")

    def __init__(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.d = json.load(f)
        except Exception:
            self.d = {}

    def get(self, k, default=""):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = v
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.d, f, ensure_ascii=False)
        except Exception:
            pass


S = Settings()


def http(params, post=None, timeout=20, raw=False):
    url = API + "?" + urllib.parse.urlencode(params)
    data = urllib.parse.urlencode(post).encode("utf-8") if post is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "CodiyaKakao/" + VERSION})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return body if raw else json.loads(body.decode("utf-8"))


def base_params(a):
    return {"a": a, "pctok": S.get("tok"), "v": VERSION}


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def open_home():
    try:
        os.startfile(HOME)
    except Exception:
        pass


# ---------------------------------------------------------------- 화면 (tkinter: 메인 스레드)
class UI:
    def __init__(self, app):
        import tkinter as tk
        self.tk = tk
        self.app = app
        self.root = tk.Tk()
        self.root.withdraw()
        self.q = queue.Queue()
        self.login_win = None
        self.pay_win = None
        self.root.after(300, self._pump)

    def call(self, fn, *a):
        self.q.put((fn, a))

    def _pump(self):
        try:
            while True:
                fn, a = self.q.get_nowait()
                try:
                    fn(*a)
                except Exception as e:
                    log.info(f"[화면 오류] {e}")
        except queue.Empty:
            pass
        self.root.after(300, self._pump)

    def _win(self, title, w, h):
        tk = self.tk
        win = tk.Toplevel(self.root)
        win.title(title)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
        try:
            win.iconbitmap(os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "app.ico"))
        except Exception:
            pass
        return win

    def show_login(self, msg=""):
        tk = self.tk
        if self.login_win is not None and self.login_win.winfo_exists():
            self.login_win.lift()
            return
        win = self.login_win = self._win("코디야 로그인 · " + APP_NAME, 380, 330)
        font = ("Malgun Gothic", 11)
        tk.Label(win, text="💬 " + APP_NAME, font=("Malgun Gothic", 15, "bold")).pack(pady=(18, 4))
        tk.Label(win, text="코디야 아이디로 로그인해 주세요", font=font, fg="#5B6B73").pack()
        frm = tk.Frame(win)
        frm.pack(pady=12)
        tk.Label(frm, text="아이디", font=font, width=7, anchor="w").grid(row=0, column=0, pady=4)
        e_id = tk.Entry(frm, font=font, width=22)
        e_id.grid(row=0, column=1)
        e_id.insert(0, S.get("last_id"))
        tk.Label(frm, text="비밀번호", font=font, width=7, anchor="w").grid(row=1, column=0, pady=4)
        e_pw = tk.Entry(frm, font=font, width=22, show="●")
        e_pw.grid(row=1, column=1)
        lb = tk.Label(win, text=msg, font=("Malgun Gothic", 10), fg="#D93025", wraplength=340)
        lb.pack()

        def do_login(_=None):
            uid, pw = e_id.get().strip(), e_pw.get()
            if not uid or not pw:
                lb.config(text="아이디와 비밀번호를 넣어 주세요")
                return
            lb.config(text="로그인 중…", fg="#5B6B73")
            win.update()
            try:
                r = http({"a": "login", "v": VERSION}, {"mb_id": uid, "mb_password": pw, "name": socket.gethostname()})
            except Exception:
                lb.config(text="인터넷 연결을 확인해 주세요", fg="#D93025")
                return
            if not r.get("ok"):
                lb.config(text=r.get("msg") or "로그인하지 못했어요", fg="#D93025")
                return
            S.set("tok", r["tok"])
            S.set("last_id", uid)
            win.destroy()
            self.login_win = None
            self.app.on_login(r.get("name", uid))

        tk.Button(win, text="로그인", font=("Malgun Gothic", 12, "bold"), bg="#0AA394", fg="white", width=20,
                  relief="flat", command=do_login).pack(pady=8)
        tk.Label(win, text="※ 비밀번호는 이 PC에 저장하지 않아요", font=("Malgun Gothic", 9), fg="#9AA6AC").pack()
        e_pw.bind("<Return>", do_login)
        e_id.bind("<Return>", lambda _: e_pw.focus_set())
        (e_pw if S.get("last_id") else e_id).focus_set()
        win.protocol("WM_DELETE_WINDOW", lambda: (win.destroy(), setattr(self, "login_win", None)))

    def show_pay(self, msg):
        tk = self.tk
        if self.pay_win is not None and self.pay_win.winfo_exists():
            self.pay_win.lift()
            return
        win = self.pay_win = self._win(APP_NAME, 400, 230)
        tk.Label(win, text="💳 결제 후 사용 가능해요", font=("Malgun Gothic", 15, "bold")).pack(pady=(22, 8))
        tk.Label(win, text=msg or "결제가 되지 않았어요. 결제 후 사용 가능해요.", font=("Malgun Gothic", 11), wraplength=360).pack(pady=4)
        tk.Label(win, text="결제가 확인되면 자동으로 다시 보내요.", font=("Malgun Gothic", 10), fg="#5B6B73").pack()
        b = tk.Frame(win)
        b.pack(pady=14)
        tk.Button(b, text="결제하러 가기", font=("Malgun Gothic", 11, "bold"), bg="#0AA394", fg="white", relief="flat", width=14,
                  command=lambda: (open_home(), win.destroy())).pack(side="left", padx=4)
        tk.Button(b, text="닫기", font=("Malgun Gothic", 11), width=8, command=win.destroy).pack(side="left", padx=4)

    def ask(self, title, msg):
        from tkinter import messagebox
        return messagebox.askyesno(title, msg, parent=self.root)

    def info(self, title, msg):
        from tkinter import messagebox
        messagebox.showinfo(title, msg, parent=self.root)


# ---------------------------------------------------------------- 프로그램
class App:
    def __init__(self):
        self.ui = UI(self)
        self.status = "시작하는 중…"
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.cfg = {"poll_sec": 60, "delay_min": 4, "delay_max": 9, "retry": 2, "retry_wait": 120,
                    "img_max": 1280, "upload_wait": 4, "upload_timeout": 180}
        self.pay_shown = ""
        self.icon = None
        self.sending = False
        self.login_prompted = False

    # ----- 트레이 아이콘
    def start_tray(self):
        import pystray
        from PIL import Image
        try:
            img = Image.open(os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "app.ico"))
        except Exception:
            img = Image.new("RGB", (64, 64), (10, 163, 148))
        menu = pystray.Menu(
            pystray.MenuItem(lambda _: self.status, None, enabled=False),
            pystray.MenuItem("코디야에서 일정·템플릿 관리", lambda: open_home(), default=True),
            pystray.MenuItem("지금 확인하기", lambda: self.wake.set()),
            pystray.MenuItem("로그인하기", lambda: self.ui.call(self.ui.show_login), visible=lambda _: not S.get("tok")),
            pystray.MenuItem("로그아웃 (다른 아이디로)", lambda: self.ui.call(self.logout)),
            pystray.MenuItem("종료", lambda: self.ui.call(self.quit)),
        )
        self.icon = pystray.Icon("CodiyaKakao", img, APP_NAME, menu)
        self.icon.run_detached()

    def set_status(self, s):
        self.status = s
        try:
            if self.icon:
                self.icon.title = (APP_NAME + " · " + s)[:120]
                self.icon.update_menu()
        except Exception:
            pass

    def notify(self, title, msg):
        try:
            if self.icon:
                self.icon.notify(msg, title)
        except Exception:
            pass

    def on_login(self, name):
        self.set_status(f"연결됨 · {name}")
        self.notify("✅ 연결됐어요", "코디야에서 정한 시간에 카카오톡으로 자동 발송해요. (오른쪽 아래 아이콘으로 켜져 있어요)")
        self.wake.set()

    def logout(self):
        if not self.ui.ask(APP_NAME, "이 PC의 연결을 해제할까요?\n(다른 아이디로 다시 로그인할 수 있어요)"):
            return
        try:
            http(base_params("unlink"))
        except Exception:
            pass
        S.set("tok", "")
        self.set_status("로그인이 필요해요")
        self.ui.show_login()

    def quit(self):
        if self.sending and not self.ui.ask(APP_NAME, "지금 보내는 중이에요. 그래도 종료할까요?"):
            return
        self.stop.set()
        self.wake.set()
        try:
            self.icon.stop()
        except Exception:
            pass
        self.ui.root.quit()

    # ----- 서버 확인 (작업 스레드)
    def worker(self):
        last_upd = 0
        while not self.stop.is_set():
            try:
                if time.time() - last_upd > 6 * 3600:
                    last_upd = time.time()
                    self.check_update()
                self.tick()
            except Exception as e:
                log.info(f"[오류] {e}")
                self.set_status("인터넷 연결을 확인하는 중…")
            self.wake.wait(max(20, int(kc.as_num(self.cfg.get("poll_sec"), 60))))
            self.wake.clear()

    def tick(self):
        if not S.get("tok"):
            self.set_status("로그인이 필요해요")
            if not self.login_prompted:  # 처음 한 번만 창을 띄우고, 닫으면 아이콘 메뉴 [로그인하기]로
                self.login_prompted = True
                self.ui.call(self.ui.show_login)
            return
        p = base_params("jobs")
        p["k"] = kc.kakao_state()
        r = http(p)
        if r.get("login"):
            S.set("tok", "")
            self.set_status("로그인이 필요해요")
            self.ui.call(self.ui.show_login, r.get("msg", ""))
            return
        if r.get("pay"):
            msg = r.get("msg", "")
            self.set_status("결제 후 사용 가능")
            today = datetime.date.today().isoformat()
            if self.pay_shown != today:  # 하루 한 번만 창으로
                self.pay_shown = today
                self.ui.call(self.ui.show_pay, msg)
            return
        self.pay_shown = ""
        if isinstance(r.get("cfg"), dict):
            self.cfg.update(r["cfg"])
        items = r.get("items") or []
        st = {"ok": "연결됨 · 대기 중", "off": "⚠️ 카카오톡이 꺼져 있어요", "login": "⚠️ 카카오톡 로그인 필요", "locked": "⚠️ 화면이 잠겨 있어요"}
        self.set_status(st.get(p["k"], "연결됨 · 대기 중") + " · " + datetime.datetime.now().strftime("%H:%M") + " 확인")
        if items:
            self.send_all(items)

    # ----- 발송
    def send_all(self, items):
        self.sending = True
        try:
            log.info(f"=== 발송 시작 {len(items)}건 (v{VERSION}, 관리자 권한: {'예' if is_admin() else '아니오'}) ===")
            self.set_status(f"보내는 중… 0/{len(items)}")
            kc.wake_display()
            kcfg = {"kakao_wait_min": 10, "image_max_px": int(kc.as_num(self.cfg.get("img_max"), 1280)),
                    "upload_wait_sec": kc.as_num(self.cfg.get("upload_wait"), 4)}
            if not kc.ensure_kakao(kcfg):
                for it in items:
                    self.report(it, False, "kakao_off", "카카오톡이 실행되어 있지 않거나 로그인되지 않았어요")
                return
            pending = list(items)
            rounds = 1 + max(0, int(kc.as_num(self.cfg.get("retry"), 2)))
            done = 0
            last_err = {}
            for rnd in range(rounds):
                if rnd > 0:
                    log.info(f"--- 실패한 {len(pending)}건 재시도 ({rnd}/{rounds - 1}) ---")
                    if self.stop.wait(kc.as_num(self.cfg.get("retry_wait"), 120)):
                        break
                    kc.wake_display()
                    kc.ensure_kakao(kcfg)
                failed = []
                for i, it in enumerate(pending):
                    if self.stop.is_set():
                        break
                    ok, code, msg, detail = self.send_one(it, kcfg)
                    if ok:
                        done += 1
                        self.report(it, True, "", "", detail)
                    else:
                        failed.append(it)
                        last_err[it["job"]] = (code, msg, detail)
                    self.set_status(f"보내는 중… {done}/{len(items)}")
                    if i < len(pending) - 1:
                        time.sleep(random.uniform(kc.as_num(self.cfg.get("delay_min"), 4), kc.as_num(self.cfg.get("delay_max"), 9)))
                pending = failed
                if not pending:
                    break
            for it in pending:
                code, msg, detail = last_err.get(it["job"], ("error", "알 수 없는 오류", ""))
                self.report(it, False, code, msg, detail)
            log.info(f"=== 완료: 성공 {done} / 실패 {len(pending)} ===")
            if pending:
                self.notify("⚠️ 일부 발송 실패", f"성공 {done} · 실패 {len(pending)} — 코디야 카톡 자동발송 화면에서 이유를 볼 수 있어요")
        finally:
            self.sending = False

    def get_image(self, it):
        if not it.get("img"):
            return None
        name = "".join(c for c in it.get("img_name", "") if c.isalnum() or c in "._") or f"tpl{it['tpl']}.jpg"
        path = os.path.join(DATA, "img", name)
        if not os.path.isfile(path):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(it["img"]).query))
            q.update(base_params("img"))
            body = http(q, raw=True, timeout=60)
            if len(body) < 100 or body[:2] != b"\xff\xd8":
                raise kc.KErr("image", "이미지를 서버에서 받지 못했어요")
            with open(path, "wb") as f:
                f.write(body)
            # 오래된 이미지 정리 (30일)
            try:
                cut = time.time() - 30 * 86400
                for f in os.listdir(os.path.join(DATA, "img")):
                    fp = os.path.join(DATA, "img", f)
                    if os.path.getmtime(fp) < cut:
                        os.remove(fp)
            except Exception:
                pass
        return path

    def send_one(self, it, kcfg):
        """결과: (성공, 실패코드, 실패문구, 상세)"""
        tag = f"{it['room']} · {it.get('tpl_name', '')}"
        log.info(f"[{tag}] 발송")
        room_hwnd = 0
        try:
            img = self.get_image(it)
            room_hwnd = kc.open_room(it["room"])
            if img:
                kc.send_image(room_hwnd, img, kcfg)
            if (it.get("text") or "").strip():
                kc.send_text(room_hwnd, it["text"])
            time.sleep(2)
            if not kc.close_room_safely(room_hwnd, kc.as_num(self.cfg.get("upload_timeout"), 180)):
                log.info("  -> 성공 (업로드가 오래 걸려 채팅방을 열어둠)")
                room_hwnd = 0
                return True, "", "", "업로드가 오래 걸려 채팅방을 열어둠"
            room_hwnd = 0
            log.info("  -> 성공")
            return True, "", "", ""
        except kc.KErr as e:
            log.info(f"  -> 실패 [{e.code}] {e.msg}")
            return False, e.code, e.msg, ""
        except Exception as e:
            log.info(f"  -> 실패 [error] {e}")
            return False, "error", "알 수 없는 오류", repr(e)[:500]
        finally:
            if room_hwnd:
                try:
                    kc.close_room_safely(room_hwnd, 30)
                except Exception:
                    pass

    def report(self, it, ok, code, msg, detail=""):
        for _ in range(3):
            try:
                http(base_params("report"), {"job": it["job"], "tpl": it["tpl"], "ok": "1" if ok else "0",
                                             "code": code, "msg": msg, "detail": detail})
                return
            except Exception:
                time.sleep(5)
        log.info("  ※ 결과를 서버에 알리지 못했어요")

    # ----- 자동 업데이트
    def check_update(self):
        try:
            req = urllib.request.Request(VER_URL + "?t=" + str(int(time.time())), headers={"User-Agent": "CodiyaKakao/" + VERSION})
            with urllib.request.urlopen(req, timeout=15) as r:
                info = json.loads(r.read().decode("utf-8"))
            ver, url = str(info.get("version", "")), str(info.get("url", ""))
            if not ver or _ver(ver) <= _ver(VERSION):
                return
            if not (url.startswith("https://api.codiya.kr/") or url.startswith("https://codiya.kr/")):
                return
            if self.sending:
                return
            key = ver + "|" + datetime.date.today().isoformat()
            if S.get("upd_try") == key:  # 오늘 이미 시도했으면 내일
                return
            S.set("upd_try", key)
            req = urllib.request.Request(url, headers={"User-Agent": "CodiyaKakao/" + VERSION})
            with urllib.request.urlopen(req, timeout=300) as r:
                body = r.read()
            if len(body) < 300 * 1024 or body[:2] != b"MZ":
                return
            f = os.path.join(os.environ.get("TEMP", DATA), f"CodiyaKakaoSetup_{ver}.exe")
            with open(f, "wb") as fp:
                fp.write(body)
            log.info(f"새 버전 {ver} 설치")
            subprocess.Popen([f, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"])
            self.ui.call(self.quit_now)
        except Exception as e:
            log.info(f"[업데이트 확인 실패] {e}")

    def quit_now(self):
        self.sending = False
        self.quit()

    def run(self):
        self.start_tray()
        threading.Thread(target=self.worker, daemon=True).start()
        self.ui.root.mainloop()


def _ver(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)


def already_running():
    h = win32event.CreateMutex(None, False, "Local\\CodiyaKakao_single")
    err = win32api.GetLastError()
    if err in (winerror.ERROR_ALREADY_EXISTS, winerror.ERROR_ACCESS_DENIED) or not h:
        return True, None
    return False, h


def main():
    setup_logging()
    tray = "/tray" in sys.argv
    running, mutex = already_running()
    if running:
        if not tray:
            open_home()  # 이미 켜져 있음 → 아이콘을 또 누르면 관리 화면 열기
        return
    if not is_admin() and "/noelev" not in sys.argv:
        mutex.Close()  # 관리자 권한으로 다시 켜기 전에 자리 비워주기
        # 카카오톡이 관리자 권한으로 돌아서, 이 프로그램도 관리자 권한이어야 키보드 입력이 들어가요.
        # 설치할 때 만든 '작업 스케줄러'(가장 높은 권한)로 다시 켜서, 매번 "예"를 누르지 않게 해요.
        try:
            r = subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True, creationflags=0x08000000)
            if r.returncode == 0:
                return
        except Exception:
            pass
        try:
            if ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv[1:] + ["/noelev"]), None, 1) > 32:
                return
        except Exception:
            pass
        running, mutex = already_running()  # 관리자 권한을 못 얻으면 그냥 이대로 실행
        if running:
            return
    App().run()


if __name__ == "__main__":
    main()
