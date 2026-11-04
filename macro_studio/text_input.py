"""Windows Unicode text input, independent of keyboard layout and Shift/AltGr."""
import ctypes

WORD, DWORD, LONG = ctypes.c_uint16, ctypes.c_uint32, ctypes.c_int32
ULONG_PTR = ctypes.c_size_t

class KeyboardInput(ctypes.Structure):
    _fields_ = [("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD),
                ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]

class MouseInput(ctypes.Structure):
    _fields_ = [("dx", LONG), ("dy", LONG), ("mouseData", DWORD),
                ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]

class HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]

class InputValue(ctypes.Union):
    _fields_ = [("ki", KeyboardInput), ("mi", MouseInput), ("hi", HardwareInput)]

class Input(ctypes.Structure):
    _fields_ = [("type", DWORD), ("value", InputValue)]

def character_events(character):
    encoded = character.encode("utf-16-le")
    units = [int.from_bytes(encoded[i:i + 2], "little") for i in range(0, len(encoded), 2)]
    events = []
    for unit in units:
        for flags in (0x0004, 0x0004 | 0x0002):  # KEYEVENTF_UNICODE, KEYEVENTF_KEYUP
            event = Input()
            event.type = 1  # INPUT_KEYBOARD
            event.value.ki.wScan = unit
            event.value.ki.dwFlags = flags
            events.append(event)
    return (Input * len(events))(*events)

class WindowsTextSender:
    def __init__(self, send_input=None):
        if send_input is None:
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            send_input = self.user32.SendInput
            send_input.argtypes = (ctypes.c_uint, ctypes.POINTER(Input), ctypes.c_int)
            send_input.restype = ctypes.c_uint
        self.send_input = send_input

    def send_character(self, character):
        events = character_events(character)
        sent = self.send_input(len(events), events, ctypes.sizeof(Input))
        if sent != len(events):
            raise RuntimeError("Windows a refusé une partie de la saisie. La séquence est arrêtée pour éviter un texte incomplet.")
