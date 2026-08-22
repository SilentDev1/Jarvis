def parse_polygon(value):
    return [tuple(map(float, p.split(","))) for p in value.split(";")]


def contains(point, polygon):
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def classify(box, zones):
    x1, _y1, x2, y2 = box
    foot = ((x1 + x2) / 2, y2)
    for name in ("interaction", "approach", "observation"):
        if contains(foot, zones[name]):
            return name
    return None
