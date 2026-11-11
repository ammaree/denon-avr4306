"""Bundle-path resolver + the pinned facts the tool needs.

Resolves data files both in a PyInstaller one-file bundle (sys._MEIPASS) and when running
from the source tree. Ships the byte-diff patch and the known-good sha256 values — NOT any
Denon firmware image.
"""
import json
import os
import sys


def _data_dir():
    # PyInstaller unpacks datas under _MEIPASS; dev runs from the package dir.
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "avrfix", "data")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def data_path(name):
    return os.path.join(_data_dir(), name)


_patch_cache = None


def load_patch():
    """The DM850I SSDP byte-diff: {original_sha256, patched_sha256, size, runs:[[off,hex]]}."""
    global _patch_cache
    if _patch_cache is None:
        with open(data_path("dm850i_ssdp.patch.json"), "r") as f:
            _patch_cache = json.load(f)
    return _patch_cache


def original_sha256():
    """sha256 the owner's extracted DM850I_x image must match (vendor 6.0.0.4)."""
    return load_patch()["original_sha256"]


def patched_sha256():
    """sha256 the patched result must match before we flash it."""
    return load_patch()["patched_sha256"]


# Denon OUI — a manufacturer fact, used to recognise the receiver on the LAN.
DENON_OUI = "00:05:CD"
