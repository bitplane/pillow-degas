"""Atari DEGAS image plugin for Pillow.

Import this module to register the DEGAS format with Pillow::

    import pillow_degas
    from PIL import Image

    img = Image.open("artwork.pi1")
"""

from pillow_degas.degas_image import DegasImageFile

__all__ = ["DegasImageFile"]
