"""Pure color temperature (circadian) calculation functions.

All functions in this module are pure - they have no side effects,
no I/O, and depend only on their inputs. They can be unit tested
without any Home Assistant dependencies.
"""

from __future__ import annotations

from .models import CircadianResult

# Default sun elevation range (degrees) for circadian calculation
DEFAULT_CIRCADIAN_ELEVATION_MIN = -20.0  # Below this = min Kelvin (warm)
DEFAULT_CIRCADIAN_ELEVATION_MAX = 60.0   # Above this = max Kelvin (cool)


def calculate_kelvin_from_elevation(
    elevation: float | None,
    min_kelvin: int,
    max_kelvin: int,
    elevation_min: float = DEFAULT_CIRCADIAN_ELEVATION_MIN,
    elevation_max: float = DEFAULT_CIRCADIAN_ELEVATION_MAX,
) -> CircadianResult:
    """Calculate color temperature in Kelvin from sun elevation.

    This is a pure function that maps sun elevation to color temperature
    using linear interpolation. Lower elevation (night/dawn) produces
    warmer (lower Kelvin) temperatures, while higher elevation (day)
    produces cooler (higher Kelvin) temperatures.

    The mapping follows circadian rhythms:
    - Night/low sun (-20° and below): Warm light (~2700K, incandescent-like)
    - Noon/high sun (60° and above): Cool light (~6500K, daylight-like)
    - In-between: Linear interpolation

    Args:
        elevation: Sun elevation in degrees (0 = horizon, 90 = zenith,
                   negative = below horizon). None if sun data unavailable.
        min_kelvin: Minimum Kelvin (warmest) at/below elevation_min
        max_kelvin: Maximum Kelvin (coolest) at/above elevation_max
        elevation_min: Elevation where min_kelvin is used (default: -20°)
        elevation_max: Elevation where max_kelvin is used (default: 60°)

    Returns:
        CircadianResult with Kelvin value and sun elevation metadata

    Raises:
        ValueError: If input parameters are invalid

    Examples:
        >>> # Night/sun below horizon - warm light
        >>> result = calculate_kelvin_from_elevation(-30, 2700, 6500)
        >>> result.kelvin
        2700

        >>> # High noon - cool daylight
        >>> result = calculate_kelvin_from_elevation(70, 2700, 6500)
        >>> result.kelvin
        6500

        >>> # Sunrise/sunset (~0°) - intermediate
        >>> result = calculate_kelvin_from_elevation(0, 2700, 6500)
        >>> result.kelvin  # About 3411K
        3411

        >>> # No sun data available - fallback to min
        >>> result = calculate_kelvin_from_elevation(None, 2700, 6500)
        >>> result.kelvin
        2700
    """
    # Input validation
    if min_kelvin >= max_kelvin:
        raise ValueError(f"min_kelvin ({min_kelvin}) must be < max_kelvin ({max_kelvin})")
    if min_kelvin < 1000:
        raise ValueError(f"min_kelvin ({min_kelvin}) must be >= 1000K")
    if elevation_min >= elevation_max:
        raise ValueError(
            f"elevation_min ({elevation_min}) must be < elevation_max ({elevation_max})"
        )

    # Handle missing elevation data - use min_kelvin as safe fallback
    if elevation is None:
        return CircadianResult(
            kelvin=min_kelvin,
            sun_elevation=None,
            source="min_fallback",
        )

    # Ensure elevation_min < elevation_max
    ele_min = min(elevation_min, elevation_max)
    ele_max = max(elevation_min, elevation_max)

    # Below minimum elevation: use min Kelvin (warm, nighttime)
    if elevation <= ele_min:
        return CircadianResult(
            kelvin=min_kelvin,
            sun_elevation=elevation,
            source="min_fallback",
        )

    # Above maximum elevation: use max Kelvin (cool, midday)
    if elevation >= ele_max:
        return CircadianResult(
            kelvin=max_kelvin,
            sun_elevation=elevation,
            source="max_fallback",
        )

    # Linear interpolation between min and max elevation
    # t = 0.0 at ele_min, t = 1.0 at ele_max
    t = (elevation - ele_min) / (ele_max - ele_min)

    # Interpolate Kelvin value
    kelvin = int(round(min_kelvin + (max_kelvin - min_kelvin) * t))

    return CircadianResult(
        kelvin=kelvin,
        sun_elevation=elevation,
        source="circadian",
    )


def clamp_kelvin(kelvin: int, min_kelvin: int, max_kelvin: int) -> int:
    """Clamp Kelvin value to valid range.

    Ensures color temperature stays within hardware-supported bounds.

    Args:
        kelvin: Input Kelvin value
        min_kelvin: Minimum allowed Kelvin
        max_kelvin: Maximum allowed Kelvin

    Returns:
        Kelvin clamped to [min_kelvin, max_kelvin]

    Examples:
        >>> clamp_kelvin(8000, 2700, 6500)
        6500
        >>> clamp_kelvin(2000, 2700, 6500)
        2700
        >>> clamp_kelvin(4000, 2700, 6500)
        4000
    """
    return max(min_kelvin, min(max_kelvin, kelvin))


def mix_kelvin(
    kelvin1: int,
    kelvin2: int,
    ratio: float,
) -> int:
    """Mix two Kelvin values with a given ratio.

    Useful for smooth transitions between color temperatures.

    Args:
        kelvin1: First Kelvin value
        kelvin2: Second Kelvin value
        ratio: Mixing ratio (0.0 = all kelvin1, 1.0 = all kelvin2)

    Returns:
        Mixed Kelvin value

    Examples:
        >>> # Halfway between warm and cool
        >>> mix_kelvin(2700, 6500, 0.5)
        4600

        >>> # Mostly warm
        >>> mix_kelvin(2700, 6500, 0.2)
        3460
    """
    clamped_ratio = max(0.0, min(1.0, ratio))
    mixed = kelvin1 + (kelvin2 - kelvin1) * clamped_ratio
    return int(round(mixed))
