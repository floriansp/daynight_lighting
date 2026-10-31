"""Pure colourimetric helpers for comparing light colours to white points.

This integration only ever *commands* a colour temperature (Kelvin). Colour
bulbs such as Philips Hue are XY-native: when told a colour temperature they
store and report the resulting colour back in the CIE 1931 ``xy`` space (and
often ``color_mode: "xy"``) rather than as a ``color_temp`` mired value.

To decide whether a reported RGB/HS/XY colour is "our own circadian white" or
"a coloured scene somebody else set", we convert the reported colour to CIE
1931 ``xy`` chromaticity and measure its distance (in the perceptually more
uniform CIE 1976 ``u'v'`` space) from the black-body locus point of the Kelvin
we commanded. A white our command produced sits almost exactly on that point;
a saturated scene or a clearly different white is far away.

All functions here are pure and depend only on their inputs.
"""

from __future__ import annotations

import math

# Distance threshold in CIE 1976 u'v'. Our own circadian white lands within
# ~0.008 (bulb white-point offset + kelvin->xy conversion error), while a
# saturated scene is 0.05+ and a ~1000 K white shift is ~0.026. This sits
# comfortably between "definitely ours" and "clearly somebody else's".
COLOR_DISTANCE_THRESHOLD_UV = 0.02


def _srgb_to_linear(c: float) -> float:
    """Linearise one sRGB channel (0.0-1.0)."""
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def rgb_to_xy(rgb: tuple[int, int, int]) -> tuple[float, float]:
    """Convert sRGB (0-255) to CIE 1931 xy chromaticity (D65)."""
    r, g, b = rgb
    rl = _srgb_to_linear(r / 255.0)
    gl = _srgb_to_linear(g / 255.0)
    bl = _srgb_to_linear(b / 255.0)

    x = 0.4124564 * rl + 0.3575761 * gl + 0.1804375 * bl
    y = 0.2126729 * rl + 0.7151522 * gl + 0.0721750 * bl
    z = 0.0193339 * rl + 0.1191920 * gl + 0.9503041 * bl

    total = x + y + z
    if total <= 0:
        return (0.0, 0.0)
    return (x / total, y / total)


def hs_to_rgb(hs: tuple[float, float]) -> tuple[int, int, int]:
    """Convert HSV (hue 0-360, saturation 0-100) to sRGB 0-255 (value=1)."""
    h, s = hs
    s_norm = s / 100.0
    c = s_norm
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = 1.0 - c

    if h < 60:
        r, g, b = c, x, 0.0
    elif h < 120:
        r, g, b = x, c, 0.0
    elif h < 180:
        r, g, b = 0.0, c, x
    elif h < 240:
        r, g, b = 0.0, x, c
    elif h < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x

    return (
        int(round((r + m) * 255)),
        int(round((g + m) * 255)),
        int(round((b + m) * 255)),
    )


def kelvin_to_rgb(kelvin: int) -> tuple[int, int, int]:
    """Approximate the black-body sRGB colour (0-255) for a Kelvin value.

    Tanner Helland's approximation, valid ~1000 K to 40000 K and most
    accurate in the 3000-10000 K range this integration uses.
    """
    temp = kelvin / 100.0

    if temp <= 66:
        red = 255.0
    else:
        red = 329.698727446 * (temp - 60) ** -0.1332047592

    if temp <= 66:
        green = 99.4708025861 * math.log(temp) - 161.1195681661
    else:
        green = 288.1221695283 * (temp - 60) ** -0.0755148492

    if temp >= 66:
        blue = 255.0
    elif temp <= 19:
        blue = 0.0
    else:
        blue = 138.5177312231 * math.log(temp - 10) - 305.0447927307

    def _clamp(value: float) -> int:
        return int(min(255.0, max(0.0, round(value))))

    return (_clamp(red), _clamp(green), _clamp(blue))


def kelvin_to_xy(kelvin: int) -> tuple[float, float]:
    """Approximate the black-body locus point in CIE 1931 xy for a Kelvin."""
    return rgb_to_xy(kelvin_to_rgb(kelvin))


def xy_to_uv(x: float, y: float) -> tuple[float, float]:
    """Convert CIE 1931 xy to CIE 1976 u'v' chromaticity."""
    denom = -2 * x + 12 * y + 3
    if denom == 0:
        return (0.0, 0.0)
    return (4 * x / denom, 9 * y / denom)


def _uv_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two colours in CIE 1976 u'v' space."""
    u1, v1 = xy_to_uv(x1, y1)
    u2, v2 = xy_to_uv(x2, y2)
    return math.hypot(u1 - u2, v1 - v2)


def color_attrs_to_xy(attrs: dict) -> tuple[float, float] | None:
    """Extract a light's reported colour as CIE 1931 xy, if it has one.

    Accepts ``rgb_color`` (0-255), ``hs_color`` (h 0-360, s 0-100) or
    ``xy_color`` (0-1). Returns ``None`` when none of them is present.
    """
    rgb = attrs.get("rgb_color")
    if rgb is not None and len(rgb) == 3:
        return rgb_to_xy((int(rgb[0]), int(rgb[1]), int(rgb[2])))

    hs = attrs.get("hs_color")
    if hs is not None and len(hs) == 2:
        return rgb_to_xy(hs_to_rgb((float(hs[0]), float(hs[1]))))

    xy = attrs.get("xy_color")
    if xy is not None and len(xy) == 2:
        return (float(xy[0]), float(xy[1]))

    return None


def color_distance_to_kelvin(attrs: dict, kelvin: int) -> float | None:
    """Distance (u'v') between a light's colour and the white at *kelvin*.

    Returns ``None`` when the light has no RGB/HS/XY colour to compare.
    """
    xy = color_attrs_to_xy(attrs)
    if xy is None:
        return None
    white = kelvin_to_xy(kelvin)
    return _uv_distance(xy[0], xy[1], white[0], white[1])
