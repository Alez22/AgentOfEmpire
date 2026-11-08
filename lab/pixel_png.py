"""@brief Minimal PNG reading and writing in pure Python (no Pillow).

Used by the map mockup (lab/tiny_town_mockup.py). Reads 8-bit indexed PNGs
(the Kenney tilesheets) and writes 8-bit RGB PNGs. Not part of the game.

Resources: a picture is held as a list of rows of (r, g, b) tuples; a
512 x 512 mockup is about 260 000 tuples, a few tens of MB in Python,
acceptable for a lab script run by hand.
"""

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunks(data: bytes):
    """@brief Yield (type, payload) for every chunk after the signature."""
    position = len(PNG_SIGNATURE)
    while position < len(data):
        (length,) = struct.unpack(">I", data[position:position + 4])
        kind = data[position + 4:position + 8]
        yield kind, data[position + 8:position + 8 + length]
        position += 12 + length


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    distance_left, distance_up, distance_up_left = abs(estimate - left), abs(estimate - up), abs(estimate - up_left)
    if distance_left <= distance_up and distance_left <= distance_up_left:
        return left
    return up if distance_up <= distance_up_left else up_left


def _unfilter(raw: bytes, width: int, height: int, bytes_per_pixel: int) -> list[bytearray]:
    """@brief Undo the per-row PNG filters (spec section 9)."""
    stride = width * bytes_per_pixel
    rows, previous, position = [], bytearray(stride), 0
    for _ in range(height):
        filter_type = raw[position]
        line = bytearray(raw[position + 1:position + 1 + stride])
        position += 1 + stride
        for i in range(stride):
            left = line[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
            up = previous[i]
            up_left = previous[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
            if filter_type == 1:
                line[i] = (line[i] + left) & 0xFF
            elif filter_type == 2:
                line[i] = (line[i] + up) & 0xFF
            elif filter_type == 3:
                line[i] = (line[i] + (left + up) // 2) & 0xFF
            elif filter_type == 4:
                line[i] = (line[i] + _paeth(left, up, up_left)) & 0xFF
        rows.append(line)
        previous = line
    return rows


def read_indexed(path: str) -> tuple[list[list[int]], list[tuple[int, int, int]], list[int]]:
    """@brief Read an 8-bit indexed PNG.
    @return (rows of palette indices, palette as RGB tuples, alpha per index).
    @throws ValueError for any other PNG kind (not needed by the mockup).
    """
    data = open(path, "rb").read()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"{path} is not a PNG")
    width = height = 0
    palette, alpha, compressed = [], [], b""
    for kind, payload in _chunks(data):
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", payload)
            if bit_depth != 8 or color_type != 3 or interlace != 0:
                raise ValueError(f"{path}: only 8-bit indexed, non-interlaced PNGs are supported")
        elif kind == b"PLTE":
            palette = [tuple(payload[i:i + 3]) for i in range(0, len(payload), 3)]
        elif kind == b"tRNS":
            alpha = list(payload)
        elif kind == b"IDAT":
            compressed += payload
    alpha += [255] * (len(palette) - len(alpha))
    rows = _unfilter(zlib.decompress(compressed), width, height, 1)
    return [list(row) for row in rows], palette, alpha


def write_rgb(path: str, pixels: list[list[tuple[int, int, int]]]) -> None:
    """@brief Write rows of (r, g, b) tuples as an 8-bit RGB PNG (no filters)."""
    height, width = len(pixels), len(pixels[0])
    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for red, green, blue in row:
            raw += bytes((red, green, blue))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    with open(path, "wb") as out:
        out.write(PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
                  + chunk(b"IEND", b""))
