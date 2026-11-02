"""Small deterministic geometry helpers for the event rules.

All coordinates are normalised to ``[0, 1]`` before comparison. Polygon tests use the
ray-casting rule; boundary tests use the sign of the cross product against a directed
line. No third-party geometry or computer-vision dependency is required, so rule tests
are fast and do not load model weights.
"""

from __future__ import annotations

import math

from app.events.zones import BoundaryLine, BoundarySide, Point, Zone

Box = tuple[float, float, float, float]


def normalise_box(box: Box, frame_width: int, frame_height: int) -> Box:
    """Convert a pixel bounding box to normalised coordinates."""
    x1, y1, x2, y2 = box
    width = max(1, frame_width)
    height = max(1, frame_height)
    return (
        x1 / width,
        y1 / height,
        x2 / width,
        y2 / height,
    )


def box_center(box: Box) -> Point:
    x1, y1, x2, y2 = box
    return Point(x=(x1 + x2) / 2.0, y=(y1 + y2) / 2.0)


def box_bottom_center(box: Box) -> Point:
    """The foot/anchor point used for boundary and room membership."""
    x1, _y1, x2, y2 = box
    return Point(x=(x1 + x2) / 2.0, y=y2)


def distance(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    """Ray-casting point-in-polygon test (boundary points may be either side)."""
    if len(polygon) < 3:
        return False
    inside = False
    x, y = point.x, point.y
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i].x, polygon[i].y
        xj, yj = polygon[j].x, polygon[j].y
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def in_zone(point: Point, zone: Zone | None) -> bool:
    return zone is not None and point_in_polygon(point, zone.polygon)


def boundary_offset(point: Point, boundary: BoundaryLine) -> float:
    """Signed normalised distance from ``point`` to the boundary line.

    Positive means the point is on the ``left`` side of the directed ``p1 -> p2``
    line; negative means the right side. Values near zero are ambiguous.
    """
    dx = boundary.p2.x - boundary.p1.x
    dy = boundary.p2.y - boundary.p1.y
    length = math.hypot(dx, dy)
    if length == 0:
        return 0.0
    cross = dx * (point.y - boundary.p1.y) - dy * (point.x - boundary.p1.x)
    return cross / length


def boundary_side(point: Point, boundary: BoundaryLine, epsilon: float) -> int:
    """Return ``1`` for the inside side, ``-1`` for outside, ``0`` when ambiguous."""
    offset = boundary_offset(point, boundary)
    if abs(offset) <= epsilon:
        return 0
    is_left = offset > 0
    inside_is_left = boundary.inside_side is BoundarySide.LEFT
    return 1 if is_left == inside_is_left else -1
