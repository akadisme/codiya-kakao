# -*- coding: utf-8 -*-
"""카카오톡 PC 조작 (KakaoSender 에서 실전 검증된 코드를 그대로 가져옴)
   실패하면 KErr(code, msg) 를 던져요. code 는 서버(kakao.lib.php kk_fail_help)의 실패 이유 코드와 같아요."""
import ctypes
import io
import logging
import ntpath
import os
import subprocess
import time

import win32api
import win32clipboard
import win32con
import win32gui
import win32process
from PIL import Image, ImageOps

log = logging.getLogger("codiya_kakao")


class KErr(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def as_num(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def screen_locked():
    """화면 잠금(로그인 화면) 상태인지: 입력 데스크톱을 못 열면 잠김"""
    try:
        h = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if not h:
            return True
        ok = ctypes.windll.user32.SwitchDesktop(h)
        ctypes.windll.user32.CloseDesktop(h)
        return not ok
    except Exception:
        return False


def kakao_state():
    """서버에 알려줄 카톡 상태: ok · off · login · locked"""
    try:
        if screen_locked():
            return "locked"
        main = find_main_window()
        if not main:
            return "off"
        return "ok" if find_search_edits(main) else "login"
    except Exception:
        return ""


KAKAO_MAIN_TITLES = ("카카오톡", "KakaoTalk")


COL_ROOM, COL_TEXT, COL_IMAGE, COL_STATUS, COL_LAST = "방이름", "문구", "이미지경로", "상태", "마지막발송일시"


def enum_top_windows():
    result = []

    def cb(h, acc):
        acc.append(h)
        return True

    win32gui.EnumWindows(cb, result)
    return result


def all_descendants(parent):
    result = []

    def cb(h, acc):
        acc.append(h)
        return True

    try:
        win32gui.EnumChildWindows(parent, cb, result)
    except win32gui.error:
        pass
    return result


def direct_children(parent, cls):
    res, h = [], 0
    while True:
        h = win32gui.FindWindowEx(parent, h, cls, None)
        if not h:
            return res
        res.append(h)


def is_kakao(h):
    try:
        return win32gui.GetClassName(h).startswith("EVA_")
    except win32gui.error:
        return False


def find_main_window():
    for h in enum_top_windows():
        if win32gui.GetWindowText(h) in KAKAO_MAIN_TITLES and is_kakao(h):
            return h
    return 0


def find_room_window(room):
    for h in enum_top_windows():
        if win32gui.GetWindowText(h) == room and is_kakao(h) and win32gui.IsWindowVisible(h):
            return h
    return 0


def set_text(h, s):
    win32api.SendMessage(h, win32con.WM_SETTEXT, 0, s)


def text_len(h):
    return win32gui.SendMessage(h, win32con.WM_GETTEXTLENGTH, 0, 0)


def get_text(h):
    n = text_len(h)
    buf = ctypes.create_unicode_buffer(n + 2)
    ctypes.windll.user32.SendMessageW(h, win32con.WM_GETTEXT, n + 2, buf)
    return buf.value


def post_key(h, vk):
    win32api.PostMessage(h, win32con.WM_KEYDOWN, vk, 0)
    time.sleep(0.05)
    win32api.PostMessage(h, win32con.WM_KEYUP, vk, 0)


def real_key(vk, ctrl=False):
    if ctrl:
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    win32api.keybd_event(vk, 0, 0, 0)
    time.sleep(0.05)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    if ctrl:
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)


def force_foreground(h):
    if win32gui.IsIconic(h):
        win32gui.ShowWindow(h, win32con.SW_RESTORE)
    # 다른 창이 포커스를 쥐고 있어도 앞으로 가져오기 위한 처리
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    for _ in range(3):
        try:
            win32gui.BringWindowToTop(h)
            win32gui.SetForegroundWindow(h)
        except win32gui.error:
            pass
        time.sleep(0.5)
        if win32gui.GetForegroundWindow() == h:
            return True
    return False


def find_kakao_exe(cfg):
    cands = [str(cfg.get("kakao_path") or "").replace("/", "\\")]
    for drive in ("C:", "D:", "E:"):
        for sub in ("Program Files (x86)", "Program Files"):
            cands.append(ntpath.join(drive + "\\", sub, "Kakao", "KakaoTalk", "KakaoTalk.exe"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cands.append(ntpath.join(local, "Kakao", "KakaoTalk", "KakaoTalk.exe"))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return ""


def launch_kakao(exe):
    try:
        subprocess.Popen([exe], cwd=os.path.dirname(exe))
        return True
    except Exception as e:
        log.info(f"  [진단] 카카오톡 실행 실패: {e}")
        return False


def ensure_kakao(cfg):
    """카톡이 꺼져 있거나 트레이(X로 닫음)에만 있으면 직접 실행해서 메인창을 띄움"""
    exe = find_kakao_exe(cfg)
    end = time.time() + as_num(cfg.get("kakao_wait_min"), 60) * 60
    last_launch = last_log = 0
    while True:
        main = find_main_window()
        if main and win32gui.IsWindowVisible(main) and find_search_edits(main):
            return True
        if time.time() >= end:
            return False
        now = time.time()
        if exe and now - last_launch > 180:
            log.info("카카오톡 메인창이 없어 카카오톡을 실행합니다" if not main else "카카오톡이 트레이에 있어 메인창을 띄웁니다")
            launch_kakao(exe)
            last_launch = now
            time.sleep(8)
            main = find_main_window()
            if main and win32gui.IsWindowVisible(main):
                time.sleep(12)  # 자동 로그인 여유
                try:
                    win32gui.ShowWindow(main, win32con.SW_MINIMIZE)
                except win32gui.error:
                    pass
            continue
        if main and not win32gui.IsWindowVisible(main):
            try:
                win32gui.ShowWindow(main, win32con.SW_SHOWMINNOACTIVE)
            except win32gui.error:
                pass
        if now - last_log > 60:
            log.info("카카오톡 실행/로그인 대기 중..." + ("" if exe else " (카카오톡 설치 위치를 못 찾음 - config의 kakao_path 확인)"))
            last_log = now
        time.sleep(10)


def find_search_edits(main):
    edits = []
    for child in direct_children(main, "EVA_ChildWindow"):
        panes = direct_children(child, "EVA_Window")
        # 보통 [0]=친구 목록, [1]=채팅 목록 -> 채팅 목록부터 시도
        for pane in panes[1:] + panes[:1]:
            edits += direct_children(pane, "Edit")
    if not edits:  # 카톡 버전이 바뀌어 구조가 다를 때 대비
        edits = [h for h in all_descendants(main) if win32gui.GetClassName(h) == "Edit"]
    return edits


def open_room(room):
    h = find_room_window(room)
    if h:
        return h
    main = find_main_window()
    if not main:
        raise KErr("kakao_off", "카카오톡 메인창 없음(실행/로그인 확인)")
    edits = find_search_edits(main)
    if not edits:
        raise KErr("kakao_login", "카톡 검색창을 찾지 못함(로그인 상태 확인)")
    for e in edits:
        set_text(e, room)
        time.sleep(1.2)
        post_key(e, win32con.VK_RETURN)
        for _ in range(24):
            time.sleep(0.25)
            h = find_room_window(room)
            if h:
                set_text(e, "")
                time.sleep(1.0)
                return h
        set_text(e, "")
    raise KErr("room", "채팅방을 찾지 못함(방이름 확인)")


def close_room_safely(h, timeout):
    """업로드가 끝나기 전에 닫으면 '전송 중인 파일' 창이 뜨고 사진이 안 가므로,
    그런 확인창이 뜨면 취소하고 기다렸다가 다시 닫음. 끝까지 안 되면 방을 열어둠."""
    pid = window_pid(h)
    end = time.time() + timeout
    waited = False
    while True:
        if not win32gui.IsWindow(h) or not win32gui.IsWindowVisible(h):
            return True
        before = visible_windows_of(pid)
        try:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        except win32gui.error:
            return True
        for _ in range(8):
            time.sleep(0.25)
            if not win32gui.IsWindow(h) or not win32gui.IsWindowVisible(h):
                break
        new = visible_windows_of(pid) - before - {h}
        if not win32gui.IsWindow(h) or not win32gui.IsWindowVisible(h):
            for d in new:
                log.info(f"  [진단] 채팅방 닫은 뒤 새 창: {describe(d)}")
            return True
        # 아직 열려 있음 = '전송 중' 확인창이 떴을 가능성 -> 취소(ESC)하고 업로드 기다림
        for d in new:
            if not waited:
                log.info(f"  [안내] 이미지 업로드 중이라 기다립니다 ({describe(d)})")
            post_key(d, win32con.VK_ESCAPE)
        waited = True
        if time.time() >= end:
            log.info("  [안내] 업로드가 오래 걸려 채팅방을 열어둡니다(나중에 다시 닫기)")
            return False
        time.sleep(5)


def find_input(room_hwnd):
    for h in all_descendants(room_hwnd):
        if win32gui.GetClassName(h).startswith("RICHEDIT"):
            return h
    raise KErr("room", "채팅 입력창을 찾지 못함")


def open_clipboard():
    for _ in range(60):  # 다른 프로그램이 잠깐 쥐고 있어도 최대 15초 기다림
        try:
            win32clipboard.OpenClipboard()
            return
        except Exception:
            time.sleep(0.25)
    raise KErr("clipboard", "클립보드를 사용할 수 없음")


_DIB_CACHE = {}


def image_to_dib(path, max_px):
    key = (path, os.path.getmtime(path), max_px)
    if key in _DIB_CACHE:
        return _DIB_CACHE[key]
    img = Image.open(path)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    if max_px and max(img.size) > max_px:
        before = img.size
        img.thumbnail((max_px, max_px), Image.LANCZOS)
        log.info(f"  [안내] 이미지가 커서 줄여서 보냄: {before[0]}x{before[1]} -> {img.size[0]}x{img.size[1]}")
    buf = io.BytesIO()
    img.save(buf, "BMP")
    dib = buf.getvalue()[14:]  # BMP 파일 헤더 제거
    _DIB_CACHE.clear()
    _DIB_CACHE[key] = dib
    return dib


def set_clipboard_image(path, max_px=1280):
    dib = image_to_dib(path, int(max_px or 0))
    open_clipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
    finally:
        win32clipboard.CloseClipboard()


def window_pid(h):
    try:
        return win32process.GetWindowThreadProcessId(h)[1]
    except Exception:
        return 0


def visible_windows_of(pid):
    return {h for h in enum_top_windows() if win32gui.IsWindowVisible(h) and window_pid(h) == pid}


def click_center(h):
    l, t, r, b = win32gui.GetWindowRect(h)
    x, y = (l + r) // 2, (t + b) // 2
    try:
        win32api.SetCursorPos((x, y))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return True
    except Exception as e:
        log.info(f"  [진단] 커서 이동 실패 -> 메시지 클릭으로 대체 ({e})")
    # 마우스 커서를 못 움직이는 상황(화면 꺼짐 등) -> 창에 직접 클릭 메시지 전송
    lp = win32api.MAKELONG((r - l) // 2, (b - t) // 2)
    win32gui.PostMessage(h, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
    time.sleep(0.05)
    win32gui.PostMessage(h, win32con.WM_LBUTTONUP, 0, lp)
    return False


def focus_input(room_hwnd, edit):
    """마우스 없이 입력창에 키보드 포커스를 직접 지정"""
    cur = win32api.GetCurrentThreadId()
    target = win32process.GetWindowThreadProcessId(room_hwnd)[0]
    attached = False
    try:
        attached = bool(ctypes.windll.user32.AttachThreadInput(cur, target, True))
        ctypes.windll.user32.SetFocus(edit)
    except Exception as e:
        log.info(f"  [진단] 포커스 지정 실패 ({e})")
    finally:
        if attached:
            ctypes.windll.user32.AttachThreadInput(cur, target, False)
    time.sleep(0.2)


ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002


def wake_display():
    """꺼진 화면을 켜고, 발송하는 동안 화면이 꺼지지 않게 유지"""
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
        win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, 1, 0, 0, 0)
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, -1, 0, 0, 0)
    except Exception:
        pass
    time.sleep(3)


def describe(h):
    try:
        return f"{win32gui.GetClassName(h)}/'{win32gui.GetWindowText(h)}'"
    except Exception:
        return str(h)


def wait_popup(room_hwnd, pid, before, seconds):
    for _ in range(int(seconds * 4)):
        time.sleep(0.25)
        new = visible_windows_of(pid) - before
        if new:
            return next(iter(new))
        fg = win32gui.GetForegroundWindow()
        if fg and fg != room_hwnd and window_pid(fg) == pid:
            return fg
        if not win32gui.IsWindowEnabled(room_hwnd):  # 모달창이 떠서 채팅방이 잠김
            return -1
    return 0


def send_image(room_hwnd, path, cfg):
    max_px = int(as_num(cfg.get("image_max_px"), 1280))
    set_clipboard_image(path, max_px)
    edit = find_input(room_hwnd)
    set_text(edit, "")
    if not force_foreground(room_hwnd):
        raise KErr("locked" if screen_locked() else "focus", "채팅방 창을 앞으로 가져오지 못함")
    click_center(edit)
    focus_input(room_hwnd, edit)
    time.sleep(0.3)

    pid = window_pid(room_hwnd)
    before = visible_windows_of(pid)

    # 방법1: Ctrl+V 키 입력
    real_key(ord("V"), ctrl=True)
    popup = wait_popup(room_hwnd, pid, before, 3)

    # 방법2: 입력창에 붙여넣기 명령 직접 전송
    if not popup:
        log.info("  [진단] Ctrl+V 반응 없음 -> 붙여넣기 명령으로 재시도")
        set_clipboard_image(path, max_px)
        win32gui.SendMessage(edit, win32con.WM_PASTE, 0, 0)
        popup = wait_popup(room_hwnd, pid, before, 3)

    if not popup:
        fg = win32gui.GetForegroundWindow()
        log.info(f"  [진단] 전경창={describe(fg)}, 입력창 글자수={text_len(edit)}")
        raise KErr("image", "이미지 전송창이 뜨지 않음")

    if popup > 0:
        log.info(f"  [진단] 전송창={describe(popup)}")
        force_foreground(popup)
    time.sleep(0.6)
    real_key(win32con.VK_RETURN)

    for _ in range(40):
        time.sleep(0.25)
        closed = (popup > 0 and (not win32gui.IsWindow(popup) or not win32gui.IsWindowVisible(popup))) or \
                 (popup == -1 and win32gui.IsWindowEnabled(room_hwnd))
        if closed:
            time.sleep(as_num(cfg.get("upload_wait_sec"), 4))  # 업로드 여유
            return
    raise KErr("upload", "이미지 전송창이 닫히지 않음")


def set_clipboard_text(text):
    open_clipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()


def send_text(room_hwnd, text):
    edit = find_input(room_hwnd)
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    # 입력창에 안내문구(예: '메시지 입력')가 잡힐 수 있어, 우리 문구 앞부분이 남아있는지로 판단
    sig = re.sub(r"\s+", "", text)[:12]

    def still_there():
        return sig and sig in re.sub(r"\s+", "", get_text(edit))

    set_text(edit, "")
    time.sleep(0.3)

    if force_foreground(room_hwnd):
        # 실제 사람처럼: 입력창 클릭 -> 붙여넣기 -> 엔터
        click_center(edit)
        focus_input(room_hwnd, edit)
        time.sleep(0.3)
        set_clipboard_text(text)
        real_key(ord("V"), ctrl=True)
        time.sleep(0.8)
        if not still_there():  # 붙여넣기가 안 됐으면 직접 입력
            set_text(edit, text)
            time.sleep(0.5)
        real_key(win32con.VK_RETURN)
    else:
        set_text(edit, text)
        time.sleep(0.6)
        post_key(edit, win32con.VK_RETURN)

    for _ in range(20):
        time.sleep(0.25)
        if not still_there():
            return
    log.info(f"  [진단] 전경창={describe(win32gui.GetForegroundWindow())}, 입력창='{get_text(edit)[:20]}'")
    raise KErr("text", "문구 전송 확인 실패")


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


