from __future__ import annotations

import base64
import zlib

from ...domain.errors import TokenParseError
from ...domain.ports import ITokenCodec

SHORT_PREFIX = "bsync_v1_"
MANUAL_PREFIX = "bsync_m1_"

# An SDP with full ICE candidates is typically 2-4 KB. 1 MB is a generous
# upper bound that prevents zip-bomb style abuse without restricting normal
# inputs.
MAX_DECOMPRESSED_BYTES = 1_000_000
# Reject obviously oversized tokens before even attempting to decompress.
MAX_TOKEN_CHARS = 50_000


class Base58TokenCodec(ITokenCodec):
    def encode_short(self, room_id: str, hmac_short: str) -> str:
        sep = "_" if hmac_short else ""
        return f"{SHORT_PREFIX}{room_id}{sep}{hmac_short}"

    def decode_short(self, token: str) -> tuple[str, str]:
        if not token.startswith(SHORT_PREFIX):
            raise TokenParseError("not a short token")
        body = token[len(SHORT_PREFIX):]
        parts = body.split("_", 1)
        if len(parts) == 1:
            return parts[0], ""
        return parts[0], parts[1]

    def encode_manual(self, sdp: str) -> str:
        compressed = zlib.compress(sdp.encode("utf-8"), level=9)
        b85 = base64.b85encode(compressed).decode("ascii")
        return f"{MANUAL_PREFIX}{b85}"

    def decode_manual(self, token: str) -> str:
        if not token.startswith(MANUAL_PREFIX):
            raise TokenParseError("not a manual token")
        if len(token) > MAX_TOKEN_CHARS:
            raise TokenParseError(
                f"manual token exceeds size limit ({len(token)} > {MAX_TOKEN_CHARS})"
            )
        body = token[len(MANUAL_PREFIX):]
        try:
            compressed = base64.b85decode(body.encode("ascii"))
        except Exception as exc:
            raise TokenParseError(f"manual token base85 decode failed: {exc}") from exc

        decomp = zlib.decompressobj()
        try:
            data = decomp.decompress(compressed, MAX_DECOMPRESSED_BYTES)
            if decomp.unconsumed_tail:
                raise TokenParseError(
                    f"manual token decompresses past {MAX_DECOMPRESSED_BYTES} bytes"
                )
            data += decomp.flush()
        except TokenParseError:
            raise
        except Exception as exc:
            raise TokenParseError(f"manual token decompress failed: {exc}") from exc

        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TokenParseError(f"manual token utf-8 decode failed: {exc}") from exc

    def is_short(self, token: str) -> bool:
        return token.startswith(SHORT_PREFIX)
