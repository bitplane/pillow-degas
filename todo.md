# TODO

## Add NEOchrome (.neo) support

NEOchrome is Atari Corporation's paint program (1985), closely related to DEGAS
but with a different header layout. The current DEGAS loader accepts .neo files
(because flags=0x0000 at offset 0 looks like resolution mode 0) but produces
garbled colours because the palette is read from the wrong offset.

### Header differences

DEGAS (32034 bytes):
- Offset 0: resolution (uint16 BE) — 0=low, 1=med, 2=high, bit 15=compressed
- Offset 2: palette[16] (32 bytes)
- Offset 34: pixel data (32000 bytes)

NEOchrome (always exactly 32128 bytes):
- Offset 0: flags (uint16 BE, always 0)
- Offset 2: resolution (uint16 BE, always 0 for 320x200x16)
- Offset 4: palette[16] (32 bytes)
- Offset 36: filename (12 bytes, ASCII)
- Offset 48: colour animation limits (uint16)
- Offset 50: colour animation speed/direction (uint16)
- Offset 52: colour animation steps (uint16)
- Offset 54: x_offset (uint16, always 0)
- Offset 56: y_offset (uint16, always 0)
- Offset 58: width (uint16, 320)
- Offset 60: height (uint16, 200)
- Offset 62: reserved (66 bytes, zeros)
- Offset 128: pixel data (32000 bytes, same planar format as DEGAS)

### How to detect

The reliable distinguisher is **file size**: NEO is always 32128 bytes. Check
file size in `_accept()` or `_open()`. A secondary check: the resolution field
at offset 2 should be 0, and bytes 36-47 should look like ASCII (filename).

### Test file

`/tmp/neo-startrek.neo` — an Enterprise schematic, 320x200x16. Currently loads
with garbled colours via the DEGAS loader. Should look like green wireframe on
black background when correctly loaded.

### What to do

1. Copy `/tmp/neo-startrek.neo` to the test data directory
2. Detect NEO files by exact file size (32128) in `_accept()` or `_open()`
3. Parse the 128-byte NEO header (palette at offset 4, not offset 2)
4. Pixel data format is identical to DEGAS low-res — same planar decoding
5. Register `.neo` extension
6. Add tests that verify correct palette colours (not garbled)

### References

- Format spec: https://wiki.multimedia.cx/index.php?title=Neochrome
- ArchiveTeam: http://fileformats.archiveteam.org/wiki/NEOchrome
- More test data: https://sembiance.com/fileFormatSamples/image/neochrome/
