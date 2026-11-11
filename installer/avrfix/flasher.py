"""The guided flash orchestrator. Wraps the verified sequence from tools/dm850_writer.py as a
state machine that EMITS events and ASKS for human decisions through callbacks, so the CLI and
GUI share one source of truth and one recovery loop. The DM850I-only guarantee is enforced by
shell.CMD_ALLOW; the image is sha-pinned before it is ever sent.
"""
import time

from . import discovery, identify, image, probe, resources, selftest, shell
from .errors import HungModule, NotReachable, WriteAborted
from .events import Info, Progress, Prompt, Result, Step
from .tftp import TftpPush

RISK_TEXT = (
    "This writes new firmware to your receiver's network module.\n"
    "• During the ~1-minute write the receiver's network drops — that is normal.\n"
    "• If something interrupts it, the module is recoverable: switch the receiver off and on, "
    "and run this again. The module's own bootloader is never touched.\n"
    "• The ONE real risk is losing mains power DURING the write — use stable power (a UPS if "
    "you can) and do NOT switch the receiver off while it is writing.\n"
    "Only continue on a receiver you own."
)


class Flasher:
    def __init__(self, ip, patched_image, *, src_ip=None, tftp_port=69, shell_port=5001,
                 served_name="DM850I_0011.bcd", on_event=None, ask=None):
        self.ip = ip
        self.image = patched_image
        self.src_ip = src_ip or discovery.source_ip_for(ip)
        self.tftp_port = tftp_port
        self.shell_port = shell_port
        self.served_name = served_name
        self.on_event = on_event or (lambda e: None)
        self.ask = ask or (lambda p: False)

    def _emit(self, ev):
        self.on_event(ev)

    # ---- phases ---------------------------------------------------------------------------
    def preflight(self):
        self._emit(Step("preflight", "Checking the receiver…"))
        rep = identify.check(self.ip)
        if rep["blocking"]:
            return Result("preflight", False, " ".join(rep["blocking"]))
        if image.sha256(self.image) != resources.patched_sha256():
            return Result("preflight", False, "internal error: the patched image is not the expected build.")
        if image.bcod_problems(self.image):
            return Result("preflight", False, "internal error: the patched image failed its integrity check.")
        note = (" " + " ".join(rep["warnings"])) if rep["warnings"] else ""
        return Result("preflight", True,
                      f"Found the receiver ({rep['mode']} mode); will send from {self.src_ip}.{note}")

    def flash(self):
        """The proven write. Raises HungModule/WriteAborted on a recoverable failure."""
        sh = shell.Shell(self.ip, self.shell_port)
        mode = sh.mode()
        self._emit(Info(f"Connected to the network module ({mode} mode)."))
        if mode == "app":
            self._emit(Step("enter_bootloader", "Putting the module into update mode…"))
            sh.send_cmd("start bootloader", expect=None)
            sh.close()
            time.sleep(8)
            sh = shell.connect_retry(self.ip, self.shell_port)
        if sh.mode() != "boot":
            sh.close()
            raise WriteAborted("the module did not enter update mode (expected the '#' prompt).")
        try:
            self._emit(Step("erase", "Preparing the module…"))
            if b"ok" not in sh.send_cmd("erase image", expect=b"ok", timeout=60).lower():
                raise WriteAborted("the module did not accept the erase step.")
            # `update image` erases the firmware image and auto-arms the TFTP receiver; it does
            # not return `ok` until after the transfer, so wait for the tftp-arm indication.
            self._emit(Step("arm", "Arming the update…"))
            if b"tftp" not in sh.send_cmd("update image", expect=b"tftp", timeout=60).lower():
                raise WriteAborted("the module did not arm its update receiver.")
            time.sleep(1)
            self._emit(Step("write", "Writing the new firmware — do NOT switch off the receiver…"))
            push = TftpPush(self.ip, self.served_name, self.image,
                            server_port=self.tftp_port, src_ip=self.src_ip)
            res = push.send(probe=False,
                            on_block=lambda d, t: self._emit(Progress("write", d, t, "blocks")))
            if not res["ack0"]:
                raise HungModule("the module did not accept the firmware transfer "
                                 f"(network path / source interface {self.src_ip}).")
            if not res["complete"]:
                raise HungModule(f"the transfer did not finish ({res.get('error')}).")
            self._emit(Step("commit", "Finishing the write (the module is saving ~2 MB)…"))
            try:
                sh._read_until(b"ok", 150)
            except OSError:
                sh.close()
                sh = shell.connect_retry(self.ip, self.shell_port, total=150)
            try:
                sh.send_cmd("start image", expect=None)
            except OSError:
                sh.close()
                sh = shell.connect_retry(self.ip, self.shell_port)
                sh.send_cmd("start image", expect=None)
            return Result("flash", True, "Firmware written; the receiver is restarting.")
        finally:
            sh.close()

    def recover_and_retry(self, max_tries=3):
        for _ in range(max_tries):
            self._emit(Info("The module stopped responding. This is recoverable — its bootloader "
                            "is untouched, so it is NOT bricked."))
            go = self.ask(Prompt("power_cycle_retry",
                                  "Switch the receiver OFF at the wall, wait ~10 seconds, switch "
                                  "it ON, then continue to retry."))
            if not go:
                return Result("recover", False, "Recovery cancelled.")
            self._emit(Step("recover", "Waiting for the module's update mode to come back…"))
            if not self._wait_boot(150):
                self._emit(Info("Did not see the module come back yet; trying again."))
                continue
            try:
                res = self.flash()
                if res.ok:
                    return res
            except (HungModule, WriteAborted, NotReachable) as e:
                self._emit(Info(f"Retry hit: {e}"))
        return Result("recover", False, "Could not complete the write after several tries.")

    def _wait_boot(self, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if probe.prompt_mode(self.ip) == "boot":
                return True
            time.sleep(2)
        return False

    def selftest_post(self):
        self._emit(Step("selftest", "Waiting for the receiver to restart, then testing the fix…"))
        probe.wait_for_app(self.ip, timeout=90)
        fixed, detail = selftest.post_flash_verdict(self.ip)
        return Result("selftest", fixed, detail)

    # ---- the whole guided run -------------------------------------------------------------
    def run(self):
        pf = self.preflight()
        self._emit(pf)
        if not pf.ok:
            return pf
        if not self.ask(Prompt("ack_risk", RISK_TEXT)):
            return Result("run", False, "Stopped at the safety notice.")
        if not self.ask(Prompt("confirm_write", "Flash the patched firmware now?")):
            return Result("run", False, "Stopped before writing. Nothing was changed.")
        try:
            fr = self.flash()
        except (HungModule, WriteAborted, NotReachable) as e:
            self._emit(Result("flash", False, str(e)))
            fr = self.recover_and_retry()
            if not fr.ok:
                return fr
        self._emit(fr)
        return self.selftest_post()
