"""Before/after self-test. The post-flash test sends the exact killer packet that hangs an
unpatched DM850 and confirms the module stays alive — a clear FIXED / not-fixed verdict.
"""
import time

from . import probe


def post_flash_verdict(ip, bursts=(5, 10), settle=(10, 20)):
    """After the app has booted, send Belkin M-SEARCH killer packets and confirm the module
    survives. Returns (fixed: bool, detail: str). An unpatched unit hangs within ~4 s."""
    if not probe.is_alive(ip, timeout=1.5):
        return False, "the receiver is not answering after the update (unexpected)."
    sent = 0
    for n, wait in zip(bursts, settle):
        probe.send_ssdp(ip, count=n)
        sent += n
        time.sleep(wait)
        if not probe.is_alive(ip, timeout=1.5):
            return False, (f"the module stopped responding after {sent} SSDP test packet(s) — "
                           "the fix did not hold. Power-cycle the receiver to recover.")
    return True, (f"the receiver survived {sent} Belkin M-SEARCH packets (the exact packet that "
                  "hangs an unpatched unit). The SSDP crash is fixed.")
