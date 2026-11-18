"""Focus the actual VALORANT game window and send one Space press."""
import ctypes
from ctypes import wintypes
import ntpath
import time


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class INPUTUNION(ctypes.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('type', wintypes.DWORD), ('data', INPUTUNION)]


def send_space_to_valorant(can_send=lambda: True):
    if not can_send():
        return False, 'Space 자동 입력이 취소되었습니다.'
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsIconic.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user.SendInput.restype = wintypes.UINT
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    def is_game(hwnd):
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return False
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            return bool(kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))) and ntpath.basename(buffer.value).lower() == 'valorant-win64-shipping.exe'
        finally:
            kernel.CloseHandle(handle)

    target = user.GetForegroundWindow()
    if not is_game(target):
        targets = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        @callback_type
        def visit(hwnd, _):
            if user.IsWindowVisible(hwnd) and is_game(hwnd):
                targets.append(hwnd)
            return True
        user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user.EnumWindows(visit, 0)
        if not targets:
            return False, '발로란트 게임 창을 찾지 못해 Space를 입력하지 않았습니다.'
        target = targets[0]
        if user.IsIconic(target):
            user.ShowWindowAsync(target, 9)
        user.SetForegroundWindow(target)
        for _ in range(10):
            if user.GetForegroundWindow() == target:
                break
            time.sleep(.03)
    if not can_send():
        return False, 'Space 자동 입력이 취소되었습니다.'
    if user.GetForegroundWindow() != target or not is_game(target):
        return False, '발로란트 창 활성화에 실패해 Space를 입력하지 않았습니다.'

    # Space scan code 0x39, with a brief hold so game input polling can observe it.
    down = INPUT(type=1, ki=KEYBDINPUT(0, 0x39, 0x0008, 0, 0))
    up = INPUT(type=1, ki=KEYBDINPUT(0, 0x39, 0x0008 | 0x0002, 0, 0))
    if user.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT)) != 1:
        return False, 'Windows가 Space 입력을 허용하지 않았습니다.'
    try:
        time.sleep(.06)
    finally:
        released = user.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
    if released != 1:
        return False, 'Space 키 해제 입력에 실패했습니다. 키 상태를 확인해 주세요.'
    return True, '발로란트 창에 Space를 한 번 입력했습니다.'
