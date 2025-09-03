import hashlib
import uuid
from typing import Optional

ALPH = "0123456789abcdefghijklmnopqrstuvwxyz"
A2I = {ch: i for i, ch in enumerate(ALPH)}
I2A = {i: ch for i, ch in enumerate(ALPH)}
MIN = 0
MAX = 35


def lexo_midpoint(left: Optional[str], right: Optional[str]) -> str:
    """Compute the LexoRank-like midpoint key between left and right.

    Implements the normative algorithm from SPEC.md section 12.
    Treat None as infinite '0' (left) or 'z' (right) as per anchors.
    """
    L = left or ""
    R = right or ""
    i = 0
    out = []
    while True:
        l = A2I[L[i]] if i < len(L) else MIN
        r = A2I[R[i]] if i < len(R) else MAX
        if l + 1 < r:
            mid = (l + r) // 2
            out.append(I2A[mid])
            return "".join(out)
        out.append(I2A[l])
        i += 1


def new_uuid() -> str:
    return str(uuid.uuid4())


def etag_from(value: str) -> str:
    """Generate a weak but stable ETag from a value."""
    h = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f'"{h[:16]}"'


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
