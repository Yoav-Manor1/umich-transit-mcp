"""Geographic calculations shared by search and vehicle tracking."""
from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Great-circle distance between two latitude/longitude points, in meters."""
    p1, p2 = radians(a_lat), radians(b_lat)
    dphi = radians(b_lat - a_lat)
    dlam = radians(b_lon - a_lon)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))
