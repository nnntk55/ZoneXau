# win_console.py — ปิด QuickEdit ของหน้าต่าง console บน Windows
# คลิกโดนหน้าต่างดำแล้ว Windows เข้าโหมด "Select" หยุดโปรแกรมทั้งตัว (bridge เคยค้างแบบนี้ 13 พ.ย.)
import os


def disable_quickedit():
    if os.name != "nt":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if not k32.GetConsoleMode(h, ctypes.byref(mode)):
            return
        ENABLE_QUICK_EDIT_MODE, ENABLE_EXTENDED_FLAGS = 0x0040, 0x0080
        k32.SetConsoleMode(h, (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS)
    except Exception as e:
        print(f"disable_quickedit err: {e}")
