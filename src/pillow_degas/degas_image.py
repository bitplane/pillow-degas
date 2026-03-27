"""Atari DEGAS image plugin for Pillow.

Supports all six DEGAS file types:
- .PI1/.PI2/.PI3 (uncompressed, 320x200/640x200/640x400)
- .PC1/.PC2/.PC3 (DEGAS Elite compressed, same resolutions)
"""

import struct

from PIL import Image, ImageFile, ImagePalette

HEADER_SIZE = 34
PIXEL_DATA_SIZE = 32000
COMPRESSED_FLAG = 0x8000
RESOLUTION_MASK = 0x0003

# resolution -> (width, height, bitplanes)
MODES = {
    0: (320, 200, 4),  # low res, 16 colors
    1: (640, 200, 2),  # medium res, 4 colors
    2: (640, 400, 1),  # high res, monochrome
}

EXTENSIONS = [".pi1", ".pi2", ".pi3", ".pc1", ".pc2", ".pc3"]

# Lookup table for 3-bit ST channel to 8-bit
_ST_CHANNEL = tuple(round(v * 255 / 7) for v in range(8))


def parse_palette(data: bytes) -> tuple[bytes, bool]:
    """Parse 32 bytes of Atari ST/STe palette data into RGB bytes.

    Returns a 768-byte palette (256 entries, only first 16 used) and a bool
    indicating whether STe extended palette bits were detected.
    """
    entries = struct.unpack(">16H", data)
    is_ste = any(e & 0x0888 for e in entries)

    rgb = bytearray(768)
    for i, entry in enumerate(entries):
        entry &= 0x0FFF
        r3 = (entry >> 8) & 7
        g3 = (entry >> 4) & 7
        b3 = entry & 7

        if is_ste:
            r = ((r3 << 1) | ((entry >> 11) & 1)) * 17
            g = ((g3 << 1) | ((entry >> 7) & 1)) * 17
            b = ((b3 << 1) | ((entry >> 3) & 1)) * 17
        else:
            r = _ST_CHANNEL[r3]
            g = _ST_CHANNEL[g3]
            b = _ST_CHANNEL[b3]

        rgb[i * 3] = r
        rgb[i * 3 + 1] = g
        rgb[i * 3 + 2] = b

    return bytes(rgb), is_ste


def deinterleave_bitplanes(data: bytes, width: int, height: int, bitplanes: int) -> bytes:
    """Convert Atari ST word-interleaved bitplane data to chunky pixel indices."""
    total_words = len(data) // 2
    words = struct.unpack(f">{total_words}H", data)

    pixels = bytearray(width * height)
    chunks_per_line = width // 16
    word_idx = 0
    pixel_idx = 0

    for _y in range(height):
        for _chunk in range(chunks_per_line):
            planes = words[word_idx : word_idx + bitplanes]
            word_idx += bitplanes

            for bit in range(16):
                shift = 15 - bit
                index = 0
                for bp, plane_word in enumerate(planes):
                    index |= ((plane_word >> shift) & 1) << bp
                pixels[pixel_idx] = index
                pixel_idx += 1

    return bytes(pixels)


def decompress_packbits(data: bytes, expected_size: int = PIXEL_DATA_SIZE) -> bytes:
    """Decompress PackBits RLE data."""
    result = bytearray()
    i = 0
    length = len(data)

    while i < length and len(result) < expected_size:
        n = data[i]
        i += 1

        if n <= 127:
            count = n + 1
            result.extend(data[i : i + count])
            i += count
        elif n >= 129:
            count = 257 - n
            if i < length:
                result.extend(bytes([data[i]]) * count)
            i += 1
        # n == 128: no-op

    return bytes(result[:expected_size])


def reinterleave(data: bytes, width: int, height: int, bitplanes: int) -> bytes:
    """Convert separated-bitplane-per-scanline to word-interleaved framebuffer format.

    DEGAS Elite compressed files decompress to a layout where each scanline has
    all bytes of bitplane 0, then all bytes of bitplane 1, etc. This converts
    that back to the Atari ST word-interleaved format where bitplane words
    alternate within each 16-pixel chunk.
    """
    bytes_per_plane = width // 8
    bytes_per_line = bytes_per_plane * bitplanes
    words_per_plane = bytes_per_plane // 2
    result = bytearray(len(data))

    for y in range(height):
        line_offset = y * bytes_per_line
        dst = line_offset
        for word_idx in range(words_per_plane):
            for bp in range(bitplanes):
                src = line_offset + bp * bytes_per_plane + word_idx * 2
                result[dst : dst + 2] = data[src : src + 2]
                dst += 2

    return bytes(result)


DEGAS_UNCOMPRESSED_SIZE = HEADER_SIZE + PIXEL_DATA_SIZE  # 32034
NEO_FILE_SIZE = 32128


def _accept(prefix: bytes) -> bool:
    """Quick check if data might be a DEGAS image."""
    if len(prefix) < 2:
        return False
    res_word = struct.unpack(">H", prefix[:2])[0]
    mode = res_word & ~COMPRESSED_FLAG
    return mode in MODES


class DegasImageFile(ImageFile.ImageFile):
    """Pillow plugin for Atari DEGAS images."""

    format = "DEGAS"
    format_description = "Atari DEGAS"

    def _open(self) -> None:
        header = self.fp.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE:
            msg = "not a DEGAS file"
            raise SyntaxError(msg)

        res_word = struct.unpack(">H", header[:2])[0]
        compressed = bool(res_word & COMPRESSED_FLAG)
        resolution = res_word & RESOLUTION_MASK

        if resolution not in MODES:
            msg = "not a DEGAS file"
            raise SyntaxError(msg)

        width, height, bitplanes = MODES[resolution]

        self.fp.seek(0, 2)
        file_size = self.fp.tell()
        self.fp.seek(HEADER_SIZE)

        if file_size == NEO_FILE_SIZE:
            msg = "not a DEGAS file"
            raise SyntaxError(msg)

        if not compressed and file_size < DEGAS_UNCOMPRESSED_SIZE:
            msg = "not a DEGAS file"
            raise SyntaxError(msg)

        palette_data, is_ste = parse_palette(header[2:HEADER_SIZE])

        self._mode = "P"
        self._size = (width, height)
        self.palette = ImagePalette.raw("RGB", palette_data)
        self.info["ste"] = is_ste
        self.info["resolution"] = resolution
        self.info["compressed"] = compressed

        self.tile = [
            ImageFile._Tile(
                "degas",
                (0, 0, width, height),
                HEADER_SIZE,
                (compressed, bitplanes),
            )
        ]


class DegasDecoder(ImageFile.PyDecoder):
    """Decoder for Atari DEGAS pixel data."""

    _pulls_fd = True

    def decode(self, buffer: bytes) -> tuple[int, int]:
        compressed, bitplanes = self.args
        width = self.state.xsize
        height = self.state.ysize

        if compressed:
            raw_data = self.fd.read()
            pixel_data = decompress_packbits(raw_data, PIXEL_DATA_SIZE)
            pixel_data = reinterleave(pixel_data, width, height, bitplanes)
        else:
            pixel_data = self.fd.read(PIXEL_DATA_SIZE)

        if len(pixel_data) < PIXEL_DATA_SIZE:
            msg = "Truncated DEGAS image data"
            raise OSError(msg)

        pixels = deinterleave_bitplanes(pixel_data, width, height, bitplanes)
        self.set_as_raw(pixels)
        return -1, 0


Image.register_open(DegasImageFile.format, DegasImageFile, _accept)
Image.register_decoder("degas", DegasDecoder)
Image.register_extensions(DegasImageFile.format, EXTENSIONS)
