"""Atari NEOchrome image plugin for Pillow.

Supports .NEO files (320x200, 16 colours, always uncompressed).
Pixel data uses the same word-interleaved bitplane format as DEGAS.
"""

import struct

from PIL import Image, ImageFile, ImagePalette

from pillow_degas.degas_image import PIXEL_DATA_SIZE, deinterleave_bitplanes, parse_palette

NEO_FILE_SIZE = 32128
NEO_HEADER_SIZE = 128
NEO_PALETTE_OFFSET = 4
NEO_PALETTE_SIZE = 32
NEO_FILENAME_OFFSET = 36
NEO_FILENAME_SIZE = 12

# NEOchrome is always low-res: 320x200, 4 bitplanes, 16 colours
NEO_WIDTH = 320
NEO_HEIGHT = 200
NEO_BITPLANES = 4


def _accept(prefix: bytes) -> bool:
    """Quick check if data might be a NEOchrome image.

    NEOchrome files always start with flags=0 and resolution=0 (four zero bytes).
    This is a necessary but not sufficient check; _open() verifies the file size.
    """
    if len(prefix) < 4:
        return False
    return prefix[:4] == b"\x00\x00\x00\x00"


class NeoImageFile(ImageFile.ImageFile):
    """Pillow plugin for Atari NEOchrome images."""

    format = "NEO"
    format_description = "Atari NEOchrome"

    def _open(self) -> None:
        self.fp.seek(0, 2)
        file_size = self.fp.tell()
        self.fp.seek(0)

        if file_size != NEO_FILE_SIZE:
            msg = "not a NEOchrome file"
            raise SyntaxError(msg)

        header = self.fp.read(NEO_HEADER_SIZE)
        if len(header) < NEO_HEADER_SIZE:
            msg = "not a NEOchrome file"
            raise SyntaxError(msg)

        flags, resolution = struct.unpack(">HH", header[:4])
        if flags != 0 or resolution != 0:
            msg = "not a NEOchrome file"
            raise SyntaxError(msg)

        palette_data, is_ste = parse_palette(header[NEO_PALETTE_OFFSET : NEO_PALETTE_OFFSET + NEO_PALETTE_SIZE])

        filename_bytes = header[NEO_FILENAME_OFFSET : NEO_FILENAME_OFFSET + NEO_FILENAME_SIZE]
        filename = filename_bytes.rstrip(b"\x00").decode("ascii", errors="replace")

        self._mode = "P"
        self._size = (NEO_WIDTH, NEO_HEIGHT)
        self.palette = ImagePalette.raw("RGB", palette_data)
        self.info["ste"] = is_ste
        self.info["resolution"] = resolution
        self.info["filename"] = filename

        self.tile = [
            ImageFile._Tile(
                "neo",
                (0, 0, NEO_WIDTH, NEO_HEIGHT),
                NEO_HEADER_SIZE,
                (NEO_BITPLANES,),
            )
        ]


class NeoDecoder(ImageFile.PyDecoder):
    """Decoder for Atari NEOchrome pixel data."""

    _pulls_fd = True

    def decode(self, buffer: bytes) -> tuple[int, int]:
        (bitplanes,) = self.args
        width = self.state.xsize
        height = self.state.ysize

        pixel_data = self.fd.read(PIXEL_DATA_SIZE)
        if len(pixel_data) < PIXEL_DATA_SIZE:
            msg = "Truncated NEOchrome image data"
            raise OSError(msg)

        pixels = deinterleave_bitplanes(pixel_data, width, height, bitplanes)
        self.set_as_raw(pixels)
        return -1, 0


Image.register_open(NeoImageFile.format, NeoImageFile, _accept)
Image.register_decoder("neo", NeoDecoder)
Image.register_extension(NeoImageFile.format, ".neo")
