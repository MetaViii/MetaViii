"""Render the profile snake from MetaViii's public GitHub contribution calendar."""

from collections import deque
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen


USERNAME = "MetaViii"
OUTPUT = Path(__file__).resolve().parents[1] / "assets" / "contributions.svg"
DAY = timedelta(days=1)


class ContributionCalendar(HTMLParser):
    def __init__(self):
        super().__init__()
        self.days = {}

    def handle_starttag(self, tag, attrs):
        if tag != "td":
            return
        cell = dict(attrs)
        if "ContributionCalendar-day" not in (cell.get("class") or "").split():
            return
        if "data-date" not in cell:
            return
        day = date.fromisoformat(cell["data-date"])
        level = int(cell["data-level"])
        if not 0 <= level <= 4 or day in self.days:
            raise ValueError(f"Invalid or duplicate contribution cell for {day}")
        self.days[day] = level


def recent_days(html, today):
    parser = ContributionCalendar()
    parser.feed(html)
    parser.close()
    last = today if today in parser.days else today - DAY
    first = last - 364 * DAY
    window = [first + i * DAY for i in range(365)]
    missing = [day for day in window if day not in parser.days]
    if missing:
        raise ValueError(f"Incomplete contribution calendar: {len(missing)} missing days, starting {missing[0]}")
    return {day: parser.days[day] for day in window}


def snake_track(foods, cols):
    body = deque([(0, 3), (-1, 3), (-2, 3), (-3, 3)], maxlen=4)
    track = [body[0]]
    eaten = {body[0]: 0} if body[0] in foods else {}
    remaining = foods - eaten.keys()

    def route(targets):
        start = body[0]
        queue = deque([start])
        previous = {start: None}
        occupied = set(list(body)[1:-1])
        while queue:
            x, y = pos = queue.popleft()
            if pos in targets:
                path = []
                while pos != start:
                    path.append(pos)
                    pos = previous[pos]
                return path[::-1]
            for dx, dy in ((1, 0), (0, 1), (0, -1), (-1, 0)):
                nxt = nx, ny = (x + dx, y + dy)
                if -1 <= nx <= cols + 5 and 0 <= ny < 7 and nxt not in previous and nxt not in occupied:
                    previous[nxt] = pos
                    queue.append(nxt)
        raise ValueError("No path to a contribution cell")

    def advance(path):
        for pos in path:
            if pos in list(body)[:-1]:
                raise ValueError("Snake route intersects its own body")
            body.appendleft(pos)
            track.append(pos)
            if pos in remaining:
                eaten[pos] = len(track) - 1
                remaining.remove(pos)

    while remaining:
        advance(route(remaining))
    advance(route({(cols + 5, body[0][1])}))
    return track, eaten


def render(days):
    first, last = min(days), max(days)
    origin = first - ((first.weekday() + 1) % 7) * DAY
    cols = (last - origin).days // 7 + 1
    calendar = {divmod((day - origin).days, 7): (day, level) for day, level in days.items()}
    foods = {pos for pos, (_, level) in calendar.items() if level}
    track, eaten = snake_track(foods, cols)
    step, square = 13, 10
    width, height = cols * step + 1, 7 * step + 1
    total = len(track) + 11
    duration = round(total * 0.125, 3)

    def xy(pos):
        return (2 + pos[0] * step, 2 + pos[1] * step)

    def paint(palette, snake):
        return "".join(f".l{i}{{fill:{color}}}" for i, color in enumerate(palette)) + f".snake{{fill:{snake}}}"

    light = paint(["#e9eff1", "#b8e3e3", "#79c8cf", "#3b9fae", "#16738c"], "#06687b")
    dark = paint(["#1e3037", "#204954", "#286b78", "#3493a2", "#68bfcc"], "#a1e3e6")
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{USERNAME} contribution snake</title>',
        f'<desc id="desc">Public contribution calendar from {first} to {last}. '
        f'The snake eats all {len(foods)} cells with contributions.</desc>',
        f'<style>{light}@media(prefers-color-scheme:dark){{{dark}}}'
        '.still{display:none}@media(prefers-reduced-motion:reduce){'
        '.motion{display:none}.still{display:inline}}</style>',
        '<defs><clipPath id="bounds"><rect width="100%" height="100%"/></clipPath></defs>',
        '<g clip-path="url(#bounds)">',
    ]
    for pos, (day, level) in sorted(calendar.items()):
        x, y = xy(pos)
        geom = f'x="{x}" y="{y}" width="{square}" height="{square}" rx="2.6"'
        svg.append(f'<rect {geom} class="l{level}"><title>{day}</title></rect>')
        if level:
            t = (eaten[pos] + 0.48) / total
            svg.append(f'<rect {geom} class="l0 motion" opacity="0">'
                       f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;{t:.6f};0.97;1" '
                       f'calcMode="discrete" dur="{duration}s" repeatCount="indefinite"/></rect>')

    history = [(-3, 3), (-2, 3), (-1, 3)] + track + [track[-1]] * 12
    for offset in (3, 2, 1, 0):
        coords = [xy(pos) for pos in history[3 - offset : 4 - offset + total]]
        values = ";".join(f"{x} {y}" for x, y in coords)
        bx, by = coords[0]
        size = 10.8 - offset * 0.50
        inset = (10 - size) / 2
        svg.append(f'<g class="motion" transform="translate({bx} {by})">'
                   f'<animateTransform attributeName="transform" type="translate" values="{values}" '
                   f'dur="{duration}s" repeatCount="indefinite"/>'
                   f'<rect class="snake" x="{inset:.2f}" y="{inset:.2f}" width="{size:.2f}" '
                   f'height="{size:.2f}" rx="3.6" opacity="{1 - offset * 0.09:.2f}"/>')
        if offset == 0:
            svg.append('<g fill="#fff"><circle cx="3" cy="3.6" r="0.8"/>'
                       '<circle cx="7" cy="3.6" r="0.8"/></g>')
        svg.append('</g>')
    # Keep the snake recognizable without motion, above the unchanged contribution cells.
    x, y = xy((cols // 2 - 3, 3))
    svg.append(f'<g class="still" transform="translate({x} {y})">'
               f'<rect class="snake" width="{3 * step + square}" height="{square}" rx="4"/>'
               f'<g fill="#fff"><circle cx="{3 * step + 6}" cy="3" r="1.1"/>'
               f'<circle cx="{3 * step + 6}" cy="7" r="1.1"/></g></g>')
    svg.append('</g></svg>')
    return "\n".join(svg) + "\n"


def main():
    request = Request(
        f"https://github.com/users/{USERNAME}/contributions",
        headers={"User-Agent": f"{USERNAME}-profile-snake", "Accept": "text/html"},
    )
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8")
    days = recent_days(html, datetime.now(timezone.utc).date())
    OUTPUT.write_bytes(render(days).encode("utf-8"))
    print(f"Rendered {len(days)} days: {min(days)} to {max(days)}")


if __name__ == "__main__":
    main()
