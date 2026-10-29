"""The canonical PNG profile against the primary specifications and independent decoders.

Reference unfiltering, Huffman-code construction and chunk parsing below are written
from RFC 1950/1951 and the W3C PNG specification, not from the encoder under test.
"""
from hashlib import sha256
from io import BytesIO
import json
import struct
import subprocess
import zlib

from PIL import Image
import pytest

from src.media import canonical_png as png


def _chunks(raw):
    position, rows = 8, []
    while position < len(raw):
        length = struct.unpack(">I", raw[position:position + 4])[0]
        kind = raw[position + 4:position + 8]
        data = raw[position + 8:position + 8 + length]
        crc = struct.unpack(">I", raw[position + 8 + length:position + 12 + length])[0]
        rows.append((kind, data, crc))
        position += 12 + length
    return rows


def _unfilter(filtered, width, height, channels):
    """W3C PNG filter types 0-4, reconstructed independently of the encoder."""
    stride, rows, previous, index = width * channels, [], bytes(width * channels), 0
    for _ in range(height):
        kind, line, index = filtered[index], bytearray(filtered[index + 1:index + 1 + stride]), index + 1 + stride
        for x in range(stride):
            a = line[x - channels] if x >= channels else 0
            b = previous[x]
            c = previous[x - channels] if x >= channels else 0
            if kind == 1:
                line[x] = (line[x] + a) & 255
            elif kind == 2:
                line[x] = (line[x] + b) & 255
            elif kind == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            else:
                assert kind == 0
        rows.append(bytes(line))
        previous = bytes(line)
    assert index == len(filtered)
    return b"".join(rows)


def _decode_independently(raw):
    rows = _chunks(raw)
    assert [kind for kind, _, _ in rows] == [b"IHDR", b"IDAT", b"IEND"]
    for kind, data, crc in rows:
        assert zlib.crc32(kind + data) == crc
    width, height, depth, colour, method, filtering, interlace = struct.unpack(">IIBBBBB", rows[0][1])
    assert (depth, method, filtering, interlace) == (8, 0, 0, 0) and colour in (2, 6)
    stream = rows[1][1]
    assert stream[:2] == b"\x78\x01" and (stream[0] * 256 + stream[1]) % 31 == 0
    filtered = zlib.decompress(stream)
    assert struct.unpack(">I", stream[-4:])[0] == zlib.adler32(filtered)
    assert stream[2] & 0b111 == 0b011  # First block: BFINAL=1, BTYPE=01 fixed Huffman.
    return width, height, colour, filtered


def _pattern(width, height, channels, seed=7):
    out, state = bytearray(), seed
    for y in range(height):
        for x in range(width):
            state = (state * 1103515245 + 12345) & 0x7fffffff
            pixel = [(x * 37 + y * 11) & 255, (state >> 16) & 255, 200 if x % 9 < 4 else 13]
            out += bytes(pixel + ([(x + y) % 256] if channels == 4 else []))
    return bytes(out)


def test_fixed_huffman_codes_match_rfc1951_canonical_construction():
    # RFC 1951 3.2.2: codes from lengths (8 for 0-143, 9 for 144-255, 7 for 256-279, 8 for 280-287).
    lengths = [8] * 144 + [9] * 112 + [7] * 24 + [8] * 8
    count = [0] * 16
    for length in lengths:
        count[length] += 1
    code, next_code = 0, [0] * 16
    for bits in range(1, 16):
        code = (code + count[bits - 1]) << 1
        next_code[bits] = code
    expected = []
    for length in lengths:
        expected.append(format(next_code[length], f"0{length}b"))
        next_code[length] += 1
    assert list(png._LITERAL) == expected[:256]
    assert png._END == expected[256]
    assert png._COPY[3] == expected[257] + "00000" and png._COPY[10] == expected[264] + "00000"
    assert png._COPY[11] == expected[265] + "0" + "00000" and png._COPY[12] == expected[265] + "1" + "00000"
    # 227..257 use code 284 with five extra bits packed LSB first; 258 is code 285.
    assert png._COPY[228] == expected[284] + "10000" + "00000"
    assert png._COPY[258] == expected[285] + "00000"
    assert sorted(png._COPY) == list(range(3, 259))


def test_bytewise_subtraction_is_modulo_256_for_every_pair():
    left = bytes(a for a in range(256) for _ in range(256))
    right = bytes(b for _ in range(256) for b in range(256))
    result = png._subtract(int.from_bytes(left, "big"), int.from_bytes(right, "big"), len(left)).to_bytes(len(left), "big")
    assert result == bytes((a - b) & 255 for a, b in zip(left, right))


def test_tiny_rgb_golden_bytes_are_exactly_specified():
    raw = bytes([255, 0, 0, 255, 0, 0, 0, 0, 255, 0, 0, 255])  # 2x2: red row, blue row.
    result = png.encode("RGB", 2, 2, raw, max_bytes=1000)
    # Hand-checked: row filters Sub/Sub (5 zeros each vs Up 4/2); first stream byte 0x63
    # carries BFINAL=1, BTYPE=01 then the first bits of literal 0x01 (code 00110001).
    assert result.hex() == (
        "89504e470d0a1a0a0000000d4948445200000002000000020802000000fdd49a73"
        "0000001349444154780163fccf00028c0c0cff1918180011120201f6264d65"
        "0000000049454e44ae426082"
    )
    assert sha256(result).hexdigest() == "d9e04dba21dea6f9e9908876a396966acacc83dece561cf02fd48075545e17e8"
    assert zlib.decompress(_chunks(result)[1][1]).hex() == "01ff0000000000010000ff000000"


@pytest.mark.parametrize("mode,channels,width,height", [
    ("RGB", 3, 1, 1), ("RGB", 3, 17, 5), ("RGBA", 4, 13, 7), ("RGB", 3, 300, 40), ("RGBA", 4, 64, 3)])
def test_independent_decoders_recover_exact_pixels(mode, channels, width, height):
    raw = _pattern(width, height, channels)
    result = png.encode(mode, width, height, raw, max_bytes=10_000_000)
    w, h, colour, filtered = _decode_independently(result)
    assert (w, h, colour) == (width, height, 2 if channels == 3 else 6)
    assert _unfilter(filtered, width, height, channels) == raw
    with Image.open(BytesIO(result)) as image:
        image.load()
        assert image.format == "PNG" and image.mode == mode and image.size == (width, height)
        assert image.tobytes() == raw
        assert png.is_canonical(result, image)
    assert png.inspect(result, max_bytes=len(result)) == (width, height, mode)


def test_every_literal_and_every_copy_length_inflates():
    # Runs of 4..259 identical bytes emit every distance-1 copy length 3..258 (RFC 1951 3.2.5).
    segment = bytes(range(256)) + b"".join(bytes([n % 251]) * n for n in range(1, 600))
    bits = "110" + png._symbols(segment) + png._END
    deflate = png._bytes(bits + "0" * (-len(bits) % 8))
    assert zlib.decompressobj(-15).decompress(deflate) == segment
    raw = (bytes(range(256)) * 3)[:765] * 8
    result = png.encode("RGB", 255, 8, raw, max_bytes=1_000_000)
    _, _, _, filtered = _decode_independently(result)
    assert _unfilter(filtered, 255, 8, 3) == raw


def test_filter_choice_is_the_documented_rule():
    width, channels = 40, 3
    flat = bytes([10, 20, 30]) * width
    ramp = bytes(v % 256 for x in range(width) for v in (x * 3, x * 5, x * 7))
    raw = ramp + ramp + flat
    _, _, _, filtered = _decode_independently(png.encode("RGB", width, 3, raw, max_bytes=100_000))
    stride = width * channels + 1
    # Row 0: Up equals raw (prior row zero) and has fewer zeros than Sub; row 1 repeats row 0
    # (Up is all zero); row 2 is flat (Sub has more zeros than Up).
    assert [filtered[i * stride] for i in range(3)] == [1, 2, 1]


def test_host_compressors_are_never_used(monkeypatch):
    raw = _pattern(120, 30, 3)
    expected = png.encode("RGB", 120, 30, raw, max_bytes=1_000_000)

    def trap(*args, **kwargs):
        raise AssertionError("host compressor used")
    monkeypatch.setattr(zlib, "compress", trap)
    monkeypatch.setattr(zlib, "compressobj", trap)
    monkeypatch.setattr(Image.Image, "save", trap)
    original = Image._getencoder

    def raw_only(mode, name, *args, **kwargs):
        if name != "raw":
            raise AssertionError("host image encoder used")
        return original(mode, name, *args, **kwargs)
    monkeypatch.setattr(Image, "_getencoder", raw_only)
    image = Image.frombytes("RGB", (120, 30), raw)
    assert png.encode("RGB", 120, 30, raw, max_bytes=1_000_000) == expected
    assert png.encode_image(image, max_bytes=1_000_000) == expected


@pytest.mark.parametrize("args,message", [
    (("P", 2, 2, bytes(4)), "unsupported PNG mode"),
    (("RGB", 0, 2, b""), "unsupported PNG dimensions"),
    (("RGB", 4097, 1, bytes(4097 * 3)), "unsupported PNG dimensions"),
    (("RGB", 2, 2.0, bytes(12)), "unsupported PNG dimensions"),
    (("RGBA", 4096, 4096, b""), "image exceeds the PNG pixel bound"),
    (("RGB", 2, 2, bytes(11)), "pixel data has the wrong length"),
    (("RGB", 2, 2, bytearray(12)), "pixel data has the wrong length"),
])
def test_unsupported_inputs_refuse_before_encoding(args, message):
    with pytest.raises(png.CanonicalPNGError, match=message):
        png.encode(*args, max_bytes=100_000)


def test_output_bound_refuses_early_and_exactly():
    raw = _pattern(200, 200, 3)
    exact = png.encode("RGB", 200, 200, raw, max_bytes=10_000_000)
    assert png.encode("RGB", 200, 200, raw, max_bytes=len(exact)) == exact
    with pytest.raises(png.CanonicalPNGError, match="exceeds its byte bound"):
        png.encode("RGB", 200, 200, raw, max_bytes=len(exact) - 1)
    with pytest.raises(png.CanonicalPNGError, match="exceeds its byte bound"):
        png.encode("RGB", 200, 200, raw, max_bytes=500)


def _rebuild(rows):
    return png.SIGNATURE + b"".join(struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d)) for k, d in rows)


def test_inspect_refuses_malformed_and_unsupported_pngs_without_decoding():
    good = png.encode("RGB", 3, 3, bytes(27), max_bytes=10_000)
    rows = [(k, d) for k, d, _ in _chunks(good)]
    header = rows[0][1]
    cases = {
        "not a PNG": b"GIF89a" + good[6:],
        "truncated PNG chunk": good[:-3],
        "PNG chunk checksum mismatch": good[:-1] + bytes([good[-1] ^ 1]),
        "data after PNG end": good + b"\x00",
        "invalid PNG header": _rebuild([(b"IHDR", header + b"\x00"), *rows[1:]]),
        "unsupported PNG pixel format": _rebuild([(b"IHDR", header[:8] + b"\x10\x02\x00\x00\x00"), *rows[1:]]),
        "unsupported critical PNG chunk": _rebuild([rows[0], (b"PLTE", b"\x00" * 3), *rows[1:]]),
        "PNG data chunks are not consecutive": _rebuild([rows[0], (b"IDAT", b""), (b"tEXt", b"a\x00b"), rows[1], rows[2]]),
        "incomplete PNG": _rebuild([rows[0], rows[2]]),
    }
    interlaced = header[:12] + b"\x01"
    cases["unsupported PNG pixel format "] = _rebuild([(b"IHDR", interlaced), *rows[1:]])
    for reason, raw in cases.items():
        with pytest.raises(png.CanonicalPNGError, match=reason.strip()):
            png.inspect(raw, max_bytes=100_000)
    with pytest.raises(png.CanonicalPNGError, match="dimensions are outside"):
        png.inspect(good, max_bytes=10_000, max_width=2)
    with pytest.raises(png.CanonicalPNGError, match="size is outside"):
        png.inspect(good, max_bytes=len(good) - 1)


def test_pillow_output_is_not_canonical_and_is_detected():
    raw = _pattern(50, 20, 3)
    image = Image.frombytes("RGB", (50, 20), raw)
    out = BytesIO()
    image.save(out, format="PNG", compress_level=9)
    assert not png.is_canonical(out.getvalue(), image)
    assert png.is_canonical(png.encode_image(image, max_bytes=100_000), image)


def test_node_zlib_inflates_the_canonical_stream():
    raw = _pattern(64, 9, 4)
    result = png.encode("RGBA", 64, 9, raw, max_bytes=100_000)
    stream = _chunks(result)[1][1]
    script = ("const z=require('node:zlib');let d='';process.stdin.on('data',c=>d+=c);process.stdin.on('end',()=>{"
              "const out=z.inflateSync(Buffer.from(JSON.parse(d),'hex'));process.stdout.write(out.toString('hex'))})")
    done = subprocess.run(["node", "-e", script], input=json.dumps(stream.hex()), capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert _unfilter(bytes.fromhex(done.stdout), 64, 9, 4) == raw
