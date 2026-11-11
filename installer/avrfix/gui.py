"""Tkinter guided GUI. Same avrfix engine and event stream as the CLI. The flash runs in a
worker thread; events and prompts are marshalled to the Tk thread through a queue.

  python -m avrfix --gui
"""
import os
import queue
import threading
import tempfile

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except Exception:                       # headless / no Tk — the CLI still works
    tk = None

from . import acquire, discovery, identify, patch
from .errors import AvrfixError
from .events import Info, Progress, Prompt, Result, Step
from .flasher import Flasher

INTRO = ("Community fix for the Denon AVR-4306 — NOT a Denon product. It fixes the SSDP crash "
         "that drops the receiver's network. The patch is applied to firmware you already own; "
         "no Denon firmware ships with this tool. No warranty — use only on a receiver you own.")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AVR-4306 Network Fix")
        self.minsize(660, 560)
        self.patched = None
        self.q = queue.Queue()
        self._build()
        self.after(100, self._poll)

    def _build(self):
        pad = dict(padx=10, pady=6)
        ttk.Label(self, text=INTRO, wraplength=620, justify="left").pack(anchor="w", **pad)

        f1 = ttk.LabelFrame(self, text="1.  Your firmware (the vendor AVR-4306 6.0.0.4 updater)")
        f1.pack(fill="x", **pad)
        self.fw_var = tk.StringVar()
        row = ttk.Frame(f1); row.pack(fill="x", padx=8, pady=6)
        ttk.Entry(row, textvariable=self.fw_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=self._browse).pack(side="left", padx=4)
        ttk.Button(f1, text="Extract & patch", command=self._do_patch).pack(anchor="w", padx=8, pady=(0, 6))
        self.fw_status = ttk.Label(f1, text="Needed: the official updater .exe, a .zip of it, or an extracted DM850I_x.flash.bin.")
        self.fw_status.pack(anchor="w", padx=8, pady=(0, 6))

        f2 = ttk.LabelFrame(self, text="2.  Your receiver")
        f2.pack(fill="x", **pad)
        row2 = ttk.Frame(f2); row2.pack(fill="x", padx=8, pady=6)
        self.ip_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.ip_var, width=20).pack(side="left")
        ttk.Button(row2, text="Find on network", command=self._discover).pack(side="left", padx=4)
        ttk.Label(f2, text="Enter the receiver's IP, or let it search.").pack(anchor="w", padx=8, pady=(0, 6))

        self.start_btn = ttk.Button(self, text="Fix my receiver", command=self._start)
        self.start_btn.pack(**pad)

        self.bar = ttk.Progressbar(self, mode="determinate")
        self.bar.pack(fill="x", **pad)
        self.log = scrolledtext.ScrolledText(self, height=12, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, **pad)

    # ---- UI helpers -----------------------------------------------------------------------
    def _write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _browse(self):
        p = filedialog.askopenfilename(title="Vendor updater or DM850I image")
        if p:
            self.fw_var.set(p)

    def _do_patch(self):
        src = self.fw_var.get().strip()
        if not src:
            messagebox.showinfo("Firmware", "Choose the vendor updater file first.")
            return
        self.fw_status.configure(text="Extracting and patching…")

        def work():
            try:
                original = acquire.extract_dm850i(src)
                self.patched = patch.apply_patch(original)
                self.q.put(("fw_ok", "Your original firmware was extracted and patched. Ready to flash."))
            except AvrfixError as e:
                self.q.put(("fw_err", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _discover(self):
        self._write("Searching for the receiver…")

        def work():
            hits = discovery.find_denon()
            self.q.put(("found", hits))
        threading.Thread(target=work, daemon=True).start()

    def _start(self):
        if not self.patched:
            messagebox.showinfo("Firmware", "Prepare the firmware first (step 1).")
            return
        ip = self.ip_var.get().strip()
        if not ip:
            messagebox.showinfo("Receiver", "Enter or find the receiver's IP (step 2).")
            return
        self.start_btn.configure(state="disabled")
        fl = Flasher(ip, self.patched, on_event=self.q.put, ask=self._ask_blocking)

        def work():
            try:
                res = fl.run()
            except AvrfixError as e:
                res = Result("run", False, str(e))
            self.q.put(("done", res))
        threading.Thread(target=work, daemon=True).start()

    def _ask_blocking(self, prompt: Prompt):
        answer = {"v": None}
        evt = threading.Event()
        self.q.put(("ask", prompt, answer, evt))
        evt.wait()
        return answer["v"]

    # ---- event pump -----------------------------------------------------------------------
    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                self._dispatch(item)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _dispatch(self, item):
        if isinstance(item, Step):
            self._write(f"• {item.human}")
        elif isinstance(item, Info):
            self._write(f"  {item.human}")
        elif isinstance(item, Progress):
            self.bar.configure(maximum=item.total, value=item.done)
        elif isinstance(item, Result):
            self._write(("OK: " if item.ok else "— ") + item.detail)
        elif isinstance(item, tuple):
            self._dispatch_tuple(item)

    def _dispatch_tuple(self, item):
        kind = item[0]
        if kind == "fw_ok":
            self.fw_status.configure(text=item[1])
        elif kind == "fw_err":
            self.fw_status.configure(text="")
            messagebox.showerror("Firmware", item[1])
        elif kind == "found":
            hits = item[1]
            if hits:
                self.ip_var.set(hits[0]["ip"])
                self._write(f"Found {hits[0]['ip']} ({hits[0]['mac']}).")
            else:
                messagebox.showinfo("Receiver", "No receiver found automatically. Enter the IP "
                                    "manually. On macOS, allow local-network access for this app.")
        elif kind == "ask":
            _, prompt, answer, evt = item
            if prompt.kind == "power_cycle_retry":
                answer["v"] = messagebox.askokcancel("Recover", prompt.human)
            else:
                answer["v"] = messagebox.askyesno("Please confirm", prompt.human)
            evt.set()
        elif kind == "done":
            res = item[1]
            self.start_btn.configure(state="normal")
            if res.ok:
                messagebox.showinfo("Fixed", "Your receiver survived the test that used to crash "
                                    "it. The SSDP fix is applied.")
            else:
                messagebox.showwarning("Not completed", res.detail)


def main():
    if tk is None:
        print("A graphical display is not available; run the command-line version instead "
              "(python -m avrfix).")
        return 1
    App().mainloop()
    return 0


if __name__ == "__main__":
    main()
