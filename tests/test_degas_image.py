"""Tests for the pillow-degas plugin."""

import io
import struct

import pytest
from PIL import Image

import pillow_degas  # noqa: F401 — registers the plugin
from pillow_degas.degas_image import (
    _ST_CHANNEL,
    _accept,
    decompress_packbits,
    deinterleave_bitplanes,
    parse_palette,
    reinterleave,
)

from .conftest import DATA_DIR


# --- palette parsing ---


def test_parse_palette_all_black():
    data = b"\x00\x00" * 16
    rgb, is_ste = parse_palette(data)
    assert not is_ste
    assert rgb[:3] == b"\x00\x00\x00"


def test_parse_palette_st_white():
    data = struct.pack(">H", 0x0777) + b"\x00\x00" * 15
    rgb, is_ste = parse_palette(data)
    assert not is_ste
    assert rgb[0] == 255
    assert rgb[1] == 255
    assert rgb[2] == 255


def test_parse_palette_st_primaries():
    entries = [0x0700, 0x0070, 0x0007]
    data = struct.pack(">16H", *(entries + [0] * 13))
    rgb, is_ste = parse_palette(data)
    assert not is_ste
    assert rgb[0:3] == bytes([255, 0, 0])  # red
    assert rgb[3:6] == bytes([0, 255, 0])  # green
    assert rgb[6:9] == bytes([0, 0, 255])  # blue


def test_parse_palette_st_channel_table():
    assert _ST_CHANNEL[0] == 0
    assert _ST_CHANNEL[7] == 255
    assert len(_ST_CHANNEL) == 8


def test_parse_palette_ste_detected():
    # Set bit 11 (R LSB) on entry 0
    entries = [0x0F00]  # bits 11=1, 10-8=7 → R=15
    data = struct.pack(">16H", *(entries + [0] * 15))
    rgb, is_ste = parse_palette(data)
    assert is_ste
    assert rgb[0] == 15 * 17  # 255


def test_parse_palette_ste_full_white():
    entries = [0x0FFF]  # all 4-bit channels maxed
    data = struct.pack(">16H", *(entries + [0] * 15))
    rgb, is_ste = parse_palette(data)
    assert is_ste
    assert rgb[0:3] == bytes([255, 255, 255])


def test_parse_palette_masks_garbage_bits():
    # Bits 12-15 are garbage; 0xF777 has no STe bits (0x0888) set,
    # and after masking to 0x0FFF gives 0x0777 = ST white
    entries = [0xF777]
    data = struct.pack(">16H", *(entries + [0] * 15))
    rgb, is_ste = parse_palette(data)
    assert not is_ste
    assert rgb[0:3] == bytes([255, 255, 255])


# --- packbits decompression ---


def test_packbits_literal_run():
    # Control byte 2 = copy next 3 bytes
    data = bytes([2, 0xAA, 0xBB, 0xCC])
    result = decompress_packbits(data, 3)
    assert result == bytes([0xAA, 0xBB, 0xCC])


def test_packbits_repeat_run():
    # Control byte 253 (= -3 signed) → repeat next byte 4 times
    data = bytes([253, 0x42])
    result = decompress_packbits(data, 4)
    assert result == bytes([0x42] * 4)


def test_packbits_mixed():
    data = bytes(
        [
            1,
            0xAA,
            0xBB,  # literal: 2 bytes
            254,
            0xCC,  # repeat: 3 times
        ]
    )
    result = decompress_packbits(data, 5)
    assert result == bytes([0xAA, 0xBB, 0xCC, 0xCC, 0xCC])


def test_packbits_noop():
    # 128 is no-op, should be skipped
    data = bytes([128, 0, 0xFF])
    result = decompress_packbits(data, 1)
    assert result == bytes([0xFF])


def test_packbits_truncates_to_expected_size():
    data = bytes([4, 1, 2, 3, 4, 5])
    result = decompress_packbits(data, 3)
    assert len(result) == 3
    assert result == bytes([1, 2, 3])


# --- bitplane deinterleaving ---


def test_deinterleave_single_bitplane():
    # 1 bitplane, 16 pixels: MSB=leftmost pixel
    # 0xAAAA = 1010101010101010
    data = struct.pack(">H", 0xAAAA)
    pixels = deinterleave_bitplanes(data, 16, 1, 1)
    expected = bytes([1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0])
    assert pixels == expected


def test_deinterleave_single_bitplane_all_set():
    data = struct.pack(">H", 0xFFFF)
    pixels = deinterleave_bitplanes(data, 16, 1, 1)
    assert all(p == 1 for p in pixels)


def test_deinterleave_two_bitplanes():
    # bp0 = 0xFFFF (all 1s), bp1 = 0x0000 (all 0s)
    # Every pixel should be index 1 (bit 0 set, bit 1 clear)
    data = struct.pack(">HH", 0xFFFF, 0x0000)
    pixels = deinterleave_bitplanes(data, 16, 1, 2)
    assert all(p == 1 for p in pixels)

    # bp0 = 0x0000, bp1 = 0xFFFF → every pixel = index 2
    data = struct.pack(">HH", 0x0000, 0xFFFF)
    pixels = deinterleave_bitplanes(data, 16, 1, 2)
    assert all(p == 2 for p in pixels)

    # Both set → index 3
    data = struct.pack(">HH", 0xFFFF, 0xFFFF)
    pixels = deinterleave_bitplanes(data, 16, 1, 2)
    assert all(p == 3 for p in pixels)


def test_deinterleave_four_bitplanes():
    # Set all 4 bitplanes → index 15
    data = struct.pack(">HHHH", 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF)
    pixels = deinterleave_bitplanes(data, 16, 1, 4)
    assert all(p == 15 for p in pixels)

    # Only bp3 set → index 8
    data = struct.pack(">HHHH", 0x0000, 0x0000, 0x0000, 0xFFFF)
    pixels = deinterleave_bitplanes(data, 16, 1, 4)
    assert all(p == 8 for p in pixels)


# --- reinterleave ---


def test_reinterleave_identity_single_bitplane():
    # With 1 bitplane, separated and interleaved are the same
    data = struct.pack(">HH", 0xAAAA, 0x5555)  # 32 pixels
    result = reinterleave(data, 32, 1, 1)
    assert result == data


def test_reinterleave_two_bitplanes():
    # Separated: [bp0_w0, bp0_w1, bp1_w0, bp1_w1] for 32 pixels
    # Interleaved: [bp0_w0, bp1_w0, bp0_w1, bp1_w1]
    separated = struct.pack(">HHHH", 0x1111, 0x2222, 0x3333, 0x4444)
    expected = struct.pack(">HHHH", 0x1111, 0x3333, 0x2222, 0x4444)
    result = reinterleave(separated, 32, 1, 2)
    assert result == expected


def test_reinterleave_four_bitplanes():
    # 16 pixels, 4 bitplanes
    # Separated: [bp0, bp1, bp2, bp3]
    # Interleaved: [bp0, bp1, bp2, bp3] — same for a single chunk!
    separated = struct.pack(">HHHH", 0xAAAA, 0xBBBB, 0xCCCC, 0xDDDD)
    expected = struct.pack(">HHHH", 0xAAAA, 0xBBBB, 0xCCCC, 0xDDDD)
    result = reinterleave(separated, 16, 1, 4)
    assert result == expected


# --- _accept ---


def test_accept_valid_uncompressed():
    for mode in (0, 1, 2):
        assert _accept(struct.pack(">H", mode))


def test_accept_valid_compressed():
    for mode in (0x8000, 0x8001, 0x8002):
        assert _accept(struct.pack(">H", mode))


def test_accept_invalid():
    assert not _accept(struct.pack(">H", 3))
    assert not _accept(struct.pack(">H", 0x8003))
    assert not _accept(struct.pack(">H", 0xFFFF))
    assert not _accept(b"\x00")
    assert not _accept(b"")


# --- integration tests with real files ---


def test_open_pi1():
    img = Image.open(DATA_DIR / "MOUSE.PI1")
    assert img.mode == "P"
    assert img.size == (320, 200)
    assert img.info["resolution"] == 0
    assert img.info["compressed"] is False
    img.load()
    # Verify we got actual pixel data
    assert img.getpixel((0, 0)) is not None


def test_open_pc1():
    img = Image.open(DATA_DIR / "AMMO.PC1")
    assert img.mode == "P"
    assert img.size == (320, 200)
    assert img.info["resolution"] == 0
    assert img.info["compressed"] is True
    img.load()


def test_open_pi2():
    img = Image.open(DATA_DIR / "VALENTIN.PI2")
    assert img.mode == "P"
    assert img.size == (640, 200)
    assert img.info["resolution"] == 1
    assert img.info["compressed"] is False
    img.load()


def test_open_pi3():
    img = Image.open(DATA_DIR / "HIDDEN.PI3")
    assert img.mode == "P"
    assert img.size == (640, 400)
    assert img.info["resolution"] == 2
    assert img.info["compressed"] is False
    img.load()


def test_open_pc3():
    img = Image.open(DATA_DIR / "CLIPART.PC3")
    assert img.mode == "P"
    assert img.size == (640, 400)
    assert img.info["resolution"] == 2
    assert img.info["compressed"] is True
    img.load()


def test_open_pc2():
    img = Image.open(DATA_DIR / "MONROE.PC2")
    assert img.mode == "P"
    assert img.size == (640, 200)
    assert img.info["resolution"] == 1
    assert img.info["compressed"] is True
    img.load()


def test_convert_to_rgb():
    img = Image.open(DATA_DIR / "MOUSE.PI1")
    rgb = img.convert("RGB")
    assert rgb.mode == "RGB"
    assert rgb.size == (320, 200)


def test_save_as_png(tmp_path):
    img = Image.open(DATA_DIR / "AMMO.PC1")
    img.load()
    out = tmp_path / "test.png"
    img.save(out)
    reloaded = Image.open(out)
    assert reloaded.size == (320, 200)


# --- rejection tests ---


def test_reject_truncated_header():
    with pytest.raises(Exception):
        Image.open(io.BytesIO(b"\x00\x00\x00"))


def test_reject_bad_resolution():
    # Resolution word 3 is invalid
    data = struct.pack(">H", 3) + b"\x00" * 32032
    with pytest.raises(Exception):
        Image.open(io.BytesIO(data))


def test_reject_undersized_uncompressed():
    # Valid resolution word but file too small
    data = struct.pack(">H", 0) + b"\x00" * 100
    with pytest.raises(Exception):
        Image.open(io.BytesIO(data))
