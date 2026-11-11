"""Apply the DM850I SSDP byte-diff to the owner's own original image.

Toolchain-free (no cross-compiler): the patch is a precomputed list of changed-byte runs
(the guard caves, the three BLs, the version stamp, and the recomputed bCoD CRCs — all
authored bytes, none of Denon's original data). We require the supplied original to match
the expected sha256, apply the runs, and assert the result matches the known-good patched
sha256 and still passes the bCoD CRC check. Any deviation raises.
"""
from . import image, resources
from .errors import PatchError, ShaMismatch


def apply_patch(original: bytes) -> bytes:
    """Return the patched DM850I bytes for a verified original, or raise."""
    spec = resources.load_patch()
    have = image.sha256(original)
    if have != spec["original_sha256"]:
        raise ShaMismatch(
            "the supplied DM850I original does not match the expected vendor 6.0.0.4 image "
            f"(got {have[:12]}…, expected {spec['original_sha256'][:12]}…). "
            "This patch only applies to the 6.0.0.4 DM850I."
        )
    if len(original) != spec["size"]:
        raise PatchError(f"original image is {len(original)} bytes, expected {spec['size']}")
    buf = bytearray(original)
    for off, hexbytes in spec["runs"]:
        new = bytes.fromhex(hexbytes)
        buf[off:off + len(new)] = new
    out = bytes(buf)
    result = image.sha256(out)
    if result != spec["patched_sha256"]:
        raise PatchError(
            "patched result did not match the known-good image "
            f"(got {result[:12]}…, expected {spec['patched_sha256'][:12]}…)"
        )
    probs = image.bcod_problems(out)
    if probs:
        raise PatchError("patched image failed the bCoD CRC check: " + "; ".join(probs))
    return out
