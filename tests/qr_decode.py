"""Dependency-light QR decoding helpers for committed PNG, SVG, and PDF artwork."""

from __future__ import annotations

from pathlib import Path
import io
import re

import png
import resvg_py
import zxingcpp


def rasterize_svg(path: Path) -> bytes:
    """Rasterize an SVG with the pinned resvg binding."""

    return resvg_py.svg_to_bytes(svg_string=path.read_text(encoding="utf-8"))


def rasterize_pdf(content: bytes) -> bytes:
    """Paint a generated vector QR PDF into an RGBA PNG for decoding."""

    media = re.search(rb"/MediaBox \[0 0 (\d+) \1\]", content)
    if media is None:
        raise AssertionError("QR PDF is missing a square MediaBox")
    page = int(media.group(1))
    start = content.index(b"stream\n") + len(b"stream\n")
    end = content.index(b"\nendstream", start)
    tokens = content[start:end].decode("ascii").split()
    filled: list[tuple[int, int, int, int, tuple[int, int, int]]] = []
    pending: list[tuple[int, int, int, int]] = []
    colour = (255, 255, 255)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "rg":
            channels = tokens[index - 3:index]
            colour = tuple(int(round(float(channel) * 255)) for channel in channels)
            index += 1
        elif token == "re":
            x, y, width, height = (int(float(value)) for value in tokens[index - 4:index])
            pending.append((x, y, width, height))
            index += 1
        elif token == "f":
            filled.extend((*rect, colour) for rect in pending)
            pending = []
            index += 1
        else:
            index += 1
    if not filled:
        raise AssertionError("QR PDF content stream has no filled rectangles")

    pixels = bytearray([255, 255, 255, 255] * page * page)
    for x, y, width, height, (red, green, blue) in filled:
        for row in range(page - (y + height), page - y):
            for column in range(x, x + width):
                offset = (row * page + column) * 4
                pixels[offset:offset + 4] = bytes((red, green, blue, 255))
    stream = io.BytesIO()
    png.Writer(page, page, greyscale=False, alpha=True).write(
        stream,
        (pixels[row:row + page * 4] for row in range(0, len(pixels), page * 4)),
    )
    return stream.getvalue()


def decode_qr_png(content: bytes) -> list[zxingcpp.Barcode]:
    """Decode PNG bytes to raw grayscale pixels, then scan them with ZXing."""

    width, height, rows, _metadata = png.Reader(bytes=content).asRGBA8()
    grayscale = bytearray(width * height)
    pixel_index = 0
    for row in rows:
        channels = bytes(row)
        for red, green, blue, alpha in zip(
            channels[0::4],
            channels[1::4],
            channels[2::4],
            channels[3::4],
            strict=True,
        ):
            red = (red * alpha + 255 * (255 - alpha) + 127) // 255
            green = (green * alpha + 255 * (255 - alpha) + 127) // 255
            blue = (blue * alpha + 255 * (255 - alpha) + 127) // 255
            grayscale[pixel_index] = (299 * red + 587 * green + 114 * blue + 500) // 1000
            pixel_index += 1
    if pixel_index != width * height:
        raise AssertionError("decoded PNG row length did not match its dimensions")

    image = memoryview(grayscale).cast("B", shape=(height, width))
    return [
        result
        for result in zxingcpp.read_barcodes(
            image,
            formats=zxingcpp.BarcodeFormat.QRCode,
        )
        if result.format == zxingcpp.BarcodeFormat.QRCode
    ]
