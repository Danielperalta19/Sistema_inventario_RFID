"""
USB HID keyboard usage codes (boot-style 8-bit keycodes) for BLE HID reports
that use [modifier, key] like HeadHodge gattServer Report1.

See: USB HID Usage Tables, Keyboard/Keypad Page (0x07).
"""

from __future__ import annotations

from typing import Iterator, Tuple

# Left Shift for uppercase / symbols that need shift on US layout
MOD_LSHIFT = 0x02

# Keyboard Enter
KEY_ENTER = 0x28

# Digit row (US HID): 1..9 then 0
_DIGIT = {
    "1": 0x1E,
    "2": 0x1F,
    "3": 0x20,
    "4": 0x21,
    "5": 0x22,
    "6": 0x23,
    "7": 0x24,
    "8": 0x25,
    "9": 0x26,
    "0": 0x27,
}

# a-z (lowercase) — first 26 keys from 0x04
def _letter_key(ch: str) -> int:
    o = ord(ch)
    if ord("a") <= o <= ord("z"):
        return 0x04 + (o - ord("a"))
    raise KeyError(ch)


def char_to_hid(ch: str) -> Tuple[int, int]:
    """
    Return (modifier, keycode) for one character.
    Supports: 0-9, a-z, A-Z, Enter (\\n, \\r), Tab (\\t).
    """
    if ch in ("\n", "\r"):
        return (0, KEY_ENTER)
    if ch == "\t":
        return (0, 0x2B)  # Tab
    if ch in _DIGIT:
        return (0, _DIGIT[ch])
    if len(ch) != 1:
        raise ValueError("expected single char")
    if ch.isdigit():
        return (0, _DIGIT[ch])
    if "a" <= ch <= "z":
        return (0, _letter_key(ch))
    if "A" <= ch <= "Z":
        return (MOD_LSHIFT, _letter_key(ch.lower()))
    raise ValueError(f"unsupported character for HID: {ch!r}")


def iter_hid_keys_for_text(text: str) -> Iterator[Tuple[int, int]]:
    for ch in text:
        try:
            yield char_to_hid(ch)
        except ValueError:
            continue
