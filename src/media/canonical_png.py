"""Canonical PNG bytes for 8-bit RGB/RGBA images, independent of the host compressor.

Profile ``canonical-png-fixed-huffman-1`` (PNG: W3C PNG 3rd edition; zlib: RFC 1950;
DEFLATE: RFC 1951). The same pixels always produce the same bytes on every host:

- Chunks are exactly IHDR, one IDAT and IEND; no ancillary metadata.
- IHDR: bit depth 8, colour type 2 (RGB) or 6 (RGBA), compression/filter/interlace 0.
- Each scanline uses filter 2 (Up) when it has strictly more zero bytes than filter
  1 (Sub); otherwise Sub. Filtering is integer arithmetic modulo 256.
- The zlib stream is header 78 01, one final fixed-Huffman DEFLATE block (BTYPE 01)
  and the big-endian Adler-32 of the filtered scanlines.
- Every run of four or more identical bytes is one literal followed by distance-1
  copies of at most 258 bytes; a remainder below the minimum copy length (3) is
  emitted as literals. Every other byte is a literal.

Standard CRC-32/Adler-32 checksum functions are used; no compression library chooses
any output byte. Dimensions, input length and output size are bounded before work.
"""
from __future__ import annotations

import re
import struct
import zlib

PROFILE = "canonical-png-fixed-huffman-1"
SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_DIMENSION = 4096
MAX_RAW_BYTES = 32 * 1024 * 1024
_CHANNELS = {"RGB": (2, 3), "RGBA": (6, 4)}
_RUN = re.compile(rb"(.)\1{3,}", re.DOTALL)


class CanonicalPNGError(ValueError):
    """Unsupported input or a bound that refuses before any transport."""


def _require(condition, reason):
    if not condition:
        raise CanonicalPNGError(reason)


def _code(value, length):
    # Huffman codes are packed most-significant bit first (RFC 1951 3.1.1).
    return format(value, f"0{length}b")


def _literal_length(symbol):
    # RFC 1951 3.2.6 fixed literal/length code.
    if symbol < 144:
        return _code(0x30 + symbol, 8)
    if symbol < 256:
        return _code(0x190 + symbol - 144, 9)
    if symbol < 280:
        return _code(symbol - 256, 7)
    return _code(0xC0 + symbol - 280, 8)


_LITERAL = tuple(_literal_length(value) for value in range(256))
_END = _literal_length(256)
# RFC 1951 3.2.5 length codes 257..285: base length and extra-bit count.
_BASE = (3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99,
         115, 131, 163, 195, 227, 258)
_EXTRA = (0,) * 8 + (1,) * 4 + (2,) * 4 + (3,) * 4 + (4,) * 4 + (5,) * 4 + (0,)


def _copy_codes():
    """Distance-1 copy for each length 3..258: length code, extra bits, distance code 0."""
    table = {}
    for index, (base, extra) in enumerate(zip(_BASE, _EXTRA)):
        symbol = 257 + index
        top = 258 if symbol == 285 else (257 if symbol == 284 else _BASE[index + 1] - 1)
        for length in range(base, top + 1):
            # Extra bits are an integer packed least-significant bit first.
            bits = format(length - base, f"0{extra}b")[::-1] if extra else ""
            table[length] = _literal_length(symbol) + bits + "00000"
    return table


_COPY = _copy_codes()


def _subtract(a, b, size):
    """Bytewise (a - b) mod 256 for two big-endian packed rows, no cross-byte borrow."""
    high = int.from_bytes(b"\x80" * size, "big")
    low = int.from_bytes(b"\x7f" * size, "big")
    every = (1 << (8 * size)) - 1
    return (((a | high) - (b & low)) ^ ((a ^ (b ^ every)) & high)) & every


def _symbols(segment):
    """Stream-order bit string for one filtered scanline (literals and distance-1 copies)."""
    parts, position = [], 0
    for match in _RUN.finditer(segment):
        start, end = match.span()
        if start > position:
            parts.append("".join(map(_LITERAL.__getitem__, segment[position:start])))
        literal = _LITERAL[segment[start]]
        parts.append(literal)
        remaining = end - start - 1
        while remaining >= 3:
            length = min(258, remaining)
            parts.append(_COPY[length])
            remaining -= length
        parts.append(literal * remaining)
        position = end
    if position < len(segment):
        parts.append("".join(map(_LITERAL.__getitem__, segment[position:])))
    return "".join(parts)


def _bytes(bits):
    """Pack a stream-order bit string (length a multiple of 8) least-significant bit first."""
    return int(bits[::-1], 2).to_bytes(len(bits) // 8, "little") if bits else b""


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def encode(mode, width, height, raw, *, max_bytes):
    """Return canonical PNG bytes for exactly ``width*height`` packed 8-bit pixels."""
    _require(mode in _CHANNELS, "unsupported PNG mode")
    colour, channels = _CHANNELS[mode]
    _require(all(type(v) is int and 1 <= v <= MAX_DIMENSION for v in (width, height)),
             "unsupported PNG dimensions")
    _require(type(max_bytes) is int and 0 < max_bytes, "invalid PNG byte bound")
    stride = width * channels
    _require(stride * height <= MAX_RAW_BYTES, "image exceeds the PNG pixel bound")
    _require(type(raw) is bytes and len(raw) == stride * height, "pixel data has the wrong length")
    budget = 8 * (max_bytes - 63)  # Signature, three chunk envelopes, IHDR data, zlib framing.
    body, pending, written, adler, previous = [], "110", 0, 1, 0  # BFINAL=1, then BTYPE=01 LSB first
    for row in range(height):
        current = int.from_bytes(raw[row * stride:(row + 1) * stride], "big")
        sub = _subtract(current, current >> (8 * channels), stride).to_bytes(stride, "big")
        up = _subtract(current, previous, stride).to_bytes(stride, "big")
        segment = (b"\x02" + up) if up.count(0) > sub.count(0) else (b"\x01" + sub)
        adler = zlib.adler32(segment, adler)
        pending += _symbols(segment)
        cut = len(pending) - len(pending) % 8
        written += cut
        _require(written <= budget, "PNG exceeds its byte bound")
        body.append(_bytes(pending[:cut]))
        pending, previous = pending[cut:], current
    pending += _END
    pending += "0" * (-len(pending) % 8)
    body.append(_bytes(pending))
    stream = b"\x78\x01" + b"".join(body) + struct.pack(">I", adler)
    header = struct.pack(">IIBBBBB", width, height, 8, colour, 0, 0, 0)
    png = SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", stream) + _chunk(b"IEND", b"")
    _require(len(png) <= max_bytes, "PNG exceeds its byte bound")
    return png


def encode_image(image, *, max_bytes):
    """Canonical bytes for an in-memory RGB/RGBA image (Pillow's raw unpacked bytes)."""
    _require(image.mode in _CHANNELS, "unsupported PNG mode")
    width, height = image.size
    _require(all(1 <= v <= MAX_DIMENSION for v in (width, height)), "unsupported PNG dimensions")
    return encode(image.mode, width, height, image.tobytes(), max_bytes=max_bytes)


def inspect(raw, *, max_bytes, max_width=MAX_DIMENSION, max_height=MAX_DIMENSION):
    """Strict chunk-level PNG header check before any decode or allocation.

    Accepts any valid 8-bit non-interlaced RGB/RGBA PNG chunk layout whose critical
    chunks and CRCs are well formed; returns (width, height, mode). Decompression
    is never performed here, so dimensions bound later pixel allocation.
    """
    _require(type(raw) is bytes and 8 + 25 + 12 <= len(raw) <= max_bytes, "PNG size is outside its bound")
    _require(raw[:8] == SIGNATURE, "not a PNG")
    position, header = 8, None
    kinds: list[bytes] = []
    while position < len(raw):
        _require(position + 12 <= len(raw), "truncated PNG chunk")
        length = struct.unpack(">I", raw[position:position + 4])[0]
        kind = raw[position + 4:position + 8]
        _require(length <= len(raw) - position - 12 and re.fullmatch(rb"[A-Za-z]{4}", kind), "invalid PNG chunk")
        data = raw[position + 8:position + 8 + length]
        crc = struct.unpack(">I", raw[position + 8 + length:position + 12 + length])[0]
        _require(zlib.crc32(kind + data) == crc, "PNG chunk checksum mismatch")
        if kind == b"IHDR":
            _require(not kinds and length == 13, "invalid PNG header")
            header = struct.unpack(">IIBBBBB", data)
        kinds.append(kind)
        position += 12 + length
        if kind == b"IEND":
            _require(length == 0 and position == len(raw), "data after PNG end")
    _require(header is not None and kinds[-1] == b"IEND" and b"IDAT" in kinds, "incomplete PNG")
    first = kinds.index(b"IDAT")
    idats = [i for i, kind in enumerate(kinds) if kind == b"IDAT"]
    _require(idats == list(range(first, first + len(idats))), "PNG data chunks are not consecutive")
    assert header is not None
    width, height, depth, colour, compression, filtering, interlace = header
    _require(depth == 8 and colour in (2, 6) and compression == filtering == interlace == 0,
             "unsupported PNG pixel format")
    _require(1 <= width <= max_width and 1 <= height <= max_height, "PNG dimensions are outside their bound")
    critical = {kind for kind in kinds if kind[:1].isupper()}
    _require(critical <= {b"IHDR", b"IDAT", b"IEND"}, "unsupported critical PNG chunk")
    return width, height, "RGB" if colour == 2 else "RGBA"


def is_canonical(raw, image):
    """True only when ``raw`` equals this profile's bytes for the decoded ``image``."""
    try:
        return encode_image(image, max_bytes=len(raw)) == raw
    except CanonicalPNGError:
        return False
