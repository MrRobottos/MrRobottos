#!/usr/bin/env python3
"""Render the GitHub profile README cards as animated SVGs.

    python scripts/render_cards.py            -> cards/*.svg  (animated)
    STATIC=1 python scripts/render_cards.py   -> cards-static/*.svg + preview.html
                                                 (final frame, no animation, for screenshots)

Cards are shown through <img>, so each file is fully self-contained: an inline <style>
block (CSS keyframes), SMIL <animate>, and Fira Code subset per card with pyftsubset and
embedded as base64 WOFF. No scripts, no external requests.

Inputs
  data/contributions.json   refreshed daily by the GitHub Action (see the workflow)
  assets/portrait.(jpg|png|webp)   optional, shown in the hero if present
  fonts/                    Fira Code WOFFs; downloaded once if missing (SIL OFL 1.1)
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# ───────────────────────────── config ─────────────────────────────
LOGIN = "MrRobottos"
NAME = "Darius Mushi"
# The hero types these in turn and loops; the last one is the line shown in static mode.
TAGLINES = [
    "Founder @ Wired Minds",
    "Robotics & Software Engineer",
    "FLL & FTC Judge",
    "FIRST Global Referee",
    "Robotics Mentor & Coach",
    "Bug Bounty Hunter",
    "I don\u2019t follow blueprints. I write them.",
]
TAGLINE = TAGLINES[-1]

# Palette and typeface taken from the current README: dark #0d1117 panels, brand red
# #E24B4A, grey #888888 labels, Fira Code. Swap these if the website uses something else.
BG = "#0d1117"
PANEL = "#161b22"
LINE = "#30363d"
TEXT = "#e6edf3"
MUTED = "#888888"
ACCENT = "#E24B4A"
AMBER = "#BA7517"  # Rogue Engineers

FONT_PKG_VERSION = "5.3.0"  # @fontsource/fira-code on the npm registry
FONT_WEIGHTS = (400, 700)

TILES = [
    dict(
        title="Wired Minds",
        text="Smart livestock tracking, AI farm dashboards and agricultural robotics.",
        where="github.com/MrRobottos/Wired-Minds",
        href="https://github.com/MrRobottos/Wired-Minds",
    ),
    dict(
        title="Rogue Engineers",
        color=AMBER,
        text="Robotics education from zero: Python, Arduino, ROS2 and FIRST.",
        where="youtube.com/@BuildLikeARouge",
        href="https://www.youtube.com/@BuildLikeARouge",
    ),
    dict(
        title="Security research",
        text="Bug bounty hunting across web apps, APIs and IoT devices.",
        where="hackerone.com/prot3an",
        href="https://hackerone.com/prot3an",
    ),
]

# Wired Minds products: (name, status label, kind, stack). kind: live | building | upcoming
PRODUCTS = [
    ("Smart GPS Livestock Collar", "Building", "building", "Python \u00b7 Arduino \u00b7 NEO-6M GPS \u00b7 C++"),
    ("AI Farm Monitoring Dashboard", "MVP live", "live", "HTML \u00b7 CSS \u00b7 JavaScript \u00b7 Python Flask"),
    ("AI Anomaly Detection Engine", "In progress", "building", "scikit-learn \u00b7 pandas \u00b7 NumPy \u00b7 Python"),
    ("ROS2 Agricultural Rover", "Upcoming", "upcoming", "ROS2 \u00b7 Gazebo \u00b7 Python"),
    ("Full IoT Integration", "Upcoming", "upcoming", "MQTT \u00b7 Flask \u00b7 Pushover API \u00b7 SQLite"),
    ("Farm Security Vision", "Upcoming", "upcoming", "OpenCV \u00b7 Python \u00b7 Motion Detection"),
]

# Official roles: (role, organisation, scope)
ROLES = [
    ("Referee & Judge", "FIRST Global Challenge",
     "World Robotics Championship \u00b7 Incheon, South Korea \u00b7 October 2026 \u00b7 190+ nations competing"),
    ("Judge", "FLL South Africa", "FIRST LEGO League \u00b7 Regional & National competitions \u00b7 2026 season"),
    ("Judge", "FTC South Africa", "FIRST Tech Challenge \u00b7 Regional competitions \u00b7 2026 season"),
    ("Mentor & Coach", "Robotics Teams",
     "Programming \u00b7 Build strategy \u00b7 Engineering process \u00b7 Team leadership & culture"),
    ("Founder", "Wired Minds", "Agritech company \u00b7 Smart livestock systems \u00b7 Building from zero"),
    ("Creator", "Rogue Engineers", "Robotics education platform \u00b7 Global audience"),
]
ROLES_NOTE = (
    "Being a judge and mentor is not just a credential - it means I understand what separates "
    "teams that win from teams that only compete. That perspective informs everything I build."
)

ROGUE_QUOTE = "Robotics is for everyone. We prove it daily."
ROGUE_TEXT = (
    "A robotics education platform built on one belief - that engineering should be accessible to every "
    "young person regardless of background, budget, or geography. Teaching Python, Arduino, ROS2, FIRST "
    "Robotics, circuit design, and robot mechanics from absolute zero. No equipment needed to start. "
    "No prerequisites. No gatekeeping."
)
ROGUE_TEACH = [
    "Python for Robotics", "Arduino & Embedded Systems", "ROS2", "Circuit Design",
    "FIRST Robotics Strategy", "Robot Mechanics", "IoT Integration", "Computer Vision", "Bug Bounty Basics",
]

SECURITY_TEXT = (
    "Security is not a separate discipline for me - it is built into everything I build. Every Wired Minds "
    "IoT device, every API endpoint, every dashboard is designed with security-first thinking because I "
    "understand what attackers look for."
)
SECURITY_FOCUS = [
    ("Web application vulnerabilities", "OWASP Top 10, business logic flaws, broken access control"),
    ("IoT security", "device communication, firmware analysis, unencrypted data streams"),
    ("Authentication & authorisation", "JWT vulnerabilities, session management, privilege escalation"),
    ("API security", "REST API fuzzing, parameter manipulation, mass assignment"),
]
SECURITY_PATH = [
    "PortSwigger Web Security Academy", "Practice on CTFs", "Bug Bounty programmes",
    "Responsible disclosure", "Building more secure products",
]

TECH = [
    ("Languages", ["Python", "JavaScript", "C++", "HTML5", "CSS3", "Bash", "SQL"]),
    ("Robotics & Embedded Systems", ["Arduino", "Raspberry Pi", "ROS2", "Tinkercad"]),
    ("AI & Machine Learning", ["scikit-learn", "Pandas", "NumPy", "OpenCV"]),
    ("Web, Backend & IoT", ["Flask", "SQLite", "PostgreSQL", "REST API", "MQTT"]),
    ("Security Toolkit", ["Burp Suite", "OWASP", "Kali Linux", "Wireshark"]),
    ("Tools & Environment", ["Git", "Linux", "VS Code", "GitHub Actions", "OBS Studio"]),
]

# 2026 mission: (done, text). Tick these by hand.
MISSION_NOTE = "Building in public. Every commit. Every failure. Every breakthrough."
MISSION = [
    (False, "Build and deploy Wired Minds smart GPS livestock collar on a real farm"),
    (False, "Complete AI anomaly detection and full IoT system integration"),
    (True, "Referee & Judge FIRST Global Challenge - Incheon, South Korea (October 2026)"),
    (True, "Judge FLL SA Regionals (Oct 17 \u00b7 Nov 7 \u00b7 Nov 28 Cape Town) and Nationals (Dec 4\u20135)"),
    (False, "Launch Rogue Engineers Zero to Robot beginner course"),
    (False, "Submit first valid bug bounty report and document the methodology"),
    (False, "Grow Wired Minds + Rogue Engineers to 400K combined followers"),
    (False, "Build from Cape Town (Nov) \u00b7 Japan (Dec) - proving location is not a limit"),
    (False, "First press coverage in TechCentral or Daily Maverick"),
    (False, "Open land savings account - the bee farm starts with the first deposit"),
]

# Page timing (seconds). Every card is its own image and starts when it loads, so the
# top-to-bottom order is baked into each card's delays.
T_HERO = 0.0
T_TILES = 1.0
T_TILE_GAP = 0.14
T_PRODUCTS = 1.9
T_ROGUE = 2.5
T_ROLES = 3.1
T_SECURITY = 3.7
T_TECH = 4.3
T_CHART = 4.9
T_REPOS = 5.8
T_REPO_GAP = 0.4
STEP = 0.08  # stagger between elements inside a card

# ───────────────────────────── paths / mode ─────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
STATIC = os.environ.get("STATIC") == "1"
OUT = ROOT / ("cards-static" if STATIC else "cards")
DATA = ROOT / "data" / "contributions.json"
FONTS = ROOT / "fonts"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ───────────────────────────── helpers ─────────────────────────────
def esc(s: str) -> str:
    return html.escape(s, quote=True)


def mix(a: str, b: str, t: float) -> str:
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def fmt_int(n: int) -> str:
    return f"{n:,}"


def fmt_date(d: dt.date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def wrap(s: str, max_chars: int, max_lines: int) -> list[str]:
    lines, cur = [], ""
    for w in s.split():
        if len(cur) + len(w) + (1 if cur else 0) <= max_chars:
            cur = f"{cur} {w}".strip()
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    # a "\u00b7" separator that lands at a line break is dropped rather than left dangling
    lines = [ln.removeprefix("\u00b7 ").removesuffix(" \u00b7") for ln in lines]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max_chars - 1].rstrip() + "\u2026"
    return lines


def nice_max(v: int) -> int:
    if v <= 0:
        return 10
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 4, 6, 8, 10):
        if v <= m * e:
            return max(2, int(m * e))
    return int(10 * e)


# ───────────────────────────── fonts ─────────────────────────────
def font_path(weight: int) -> Path:
    return FONTS / f"fira-code-latin-{weight}-normal.woff"


def ensure_fonts() -> None:
    need = [font_path(w) for w in FONT_WEIGHTS]
    if all(p.exists() for p in need):
        return
    FONTS.mkdir(exist_ok=True)
    url = f"https://registry.npmjs.org/@fontsource/fira-code/-/fira-code-{FONT_PKG_VERSION}.tgz"
    print(f"downloading Fira Code {FONT_PKG_VERSION} ...")
    blob = urllib.request.urlopen(url, timeout=60).read()
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        for p in need:
            member = tf.extractfile(f"package/files/{p.name}")
            assert member is not None, p.name
            p.write_bytes(member.read())


def font_metrics():
    from fontTools.ttLib import TTFont

    f = TTFont(font_path(400))
    cmap = f.getBestCmap()
    adv = f["hmtx"][cmap[ord("a")]][0] / f["head"].unitsPerEm
    return adv, set(cmap)


ADV, GLYPHS = 0.6, set()  # filled in main()


def subset_b64(weight: int, chars: set[str]) -> str:
    text = "".join(sorted(chars | {" "}))
    missing = [c for c in text if ord(c) not in GLYPHS]
    if missing:
        print(f"  warning: glyphs missing from font: {''.join(missing)!r}")
    exe = shutil.which("pyftsubset") or None
    cmd = [exe] if exe else [sys.executable, "-m", "fontTools.subset"]
    with tempfile.TemporaryDirectory() as td:
        tfile, out = Path(td) / "chars.txt", Path(td) / "out.woff"
        tfile.write_text(text, encoding="utf-8")
        subprocess.run(
            cmd
            + [
                str(font_path(weight)),
                f"--text-file={tfile}",
                "--flavor=woff",
                "--layout-features=kern",
                "--no-hinting",
                "--name-IDs=",
                f"--output-file={out}",
            ],
            check=True,
        )
        return base64.b64encode(out.read_bytes()).decode()


# ───────────────────────────── data ─────────────────────────────
def load_data() -> dict:
    if not DATA.exists():
        sys.exit(f"missing {DATA.relative_to(ROOT)} - run the refresh step of the workflow first")
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    user = (raw.get("data") or {}).get("user")
    if user:  # raw GitHub GraphQL response
        weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
        days = [(d["date"], d["contributionCount"]) for w in weeks for d in w["contributionDays"]]
        repos = []
        for n in (user.get("pinnedItems") or {}).get("nodes") or []:
            if not n:
                continue
            lang = n.get("primaryLanguage") or {}
            repos.append(
                dict(
                    name=n["name"], url=n["url"], description=n.get("description") or "",
                    stars=n.get("stargazerCount", 0), forks=n.get("forkCount", 0),
                    language=lang.get("name"), color=lang.get("color"),
                )
            )
    else:  # flat shape: {"days": [{"date", "count"}], "repos": [...]}
        days = [(d["date"], d["count"]) for d in raw["days"]]
        repos = raw.get("repos", [])
    days = sorted((dt.date.fromisoformat(d), int(c)) for d, c in days)
    if not days:
        sys.exit("contributions.json has no days")
    updated = raw.get("generated_at", "")[:10] or days[-1][0].isoformat()
    return dict(days=days, repos=repos, updated=updated)


def compute_stats(days: list[tuple[dt.date, int]]) -> dict:
    total = sum(c for _, c in days)
    active = sum(1 for _, c in days if c > 0)
    busiest = max(days, key=lambda x: x[1])
    longest = run = 0
    prev = None
    for d, c in days:
        run = run + 1 if c > 0 and prev is not None and (d - prev).days == 1 and run else (1 if c > 0 else 0)
        longest = max(longest, run)
        prev = d
    # current streak: today at 0 doesn't break it yet, same as GitHub
    i = len(days) - 1
    if days[i][1] == 0:
        i -= 1
    cur = 0
    while i >= 0 and days[i][1] > 0:
        cur += 1
        if i > 0 and (days[i][0] - days[i - 1][0]).days != 1:
            break
        i -= 1
    return dict(total=total, active=active, busiest=busiest, longest=longest, current=cur)


def monthly(days: list[tuple[dt.date, int]]) -> list[tuple[int, int, int]]:
    last = days[-1][0]
    keys = []
    y, m = last.year, last.month
    for _ in range(12):
        keys.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    keys.reverse()
    sums = {k: 0 for k in keys}
    for d, c in days:
        if (d.year, d.month) in sums:
            sums[(d.year, d.month)] += c
    return [(y, m, sums[(y, m)]) for y, m in keys]


def load_portrait() -> str | None:
    for ext in ("jpg", "jpeg", "png", "webp"):
        p = ROOT / "assets" / f"portrait.{ext}"
        if not p.exists():
            continue
        try:
            from PIL import Image

            im = Image.open(p).convert("RGB")
            s = min(im.size)
            l, t = (im.width - s) // 2, (im.height - s) // 2
            im = im.crop((l, t, l + s, t + s)).resize((224, 224))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=84, optimize=True)
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        except ImportError:
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
    return None


# ───────────────────────────── card scaffold ─────────────────────────────
class Card:
    def __init__(self, name: str, w: int, h: int, title: str, base: float):
        self.name, self.w, self.h, self.title, self.base = name, w, h, title, base
        self.chars: dict[int, set[str]] = {w_: set() for w_ in FONT_WEIGHTS}
        self.body: list[str] = []
        self.defs: list[str] = []
        self._n = 0

    def delay(self, extra: float = 0.0) -> float:
        v = self.base + extra + self._n * STEP
        self._n += 1
        return v

    def t(self, x, y, s, size=13, weight=400, fill=TEXT, anchor="start") -> str:
        self.chars[weight].update(s)
        a = "" if anchor == "start" else f' text-anchor="{anchor}"'
        return f'<text x="{x:g}" y="{y:g}" font-size="{size}" font-weight="{weight}" fill="{fill}"{a}>{esc(s)}</text>'

    def rise(self, inner: str, at: float | None = None) -> str:
        if STATIC:
            return inner
        d = self.delay() if at is None else at
        return f'<g class="rise" style="animation-delay:{d:.2f}s">{inner}</g>'

    def add(self, *parts: str) -> None:
        self.body.extend(parts)

    def css(self) -> str:
        faces = "".join(
            "@font-face{font-family:FC;font-style:normal;font-weight:%d;"
            "src:url(data:font/woff;base64,%s) format('woff')}" % (w, subset_b64(w, ch))
            for w, ch in self.chars.items()
            if ch
        )
        base = (
            "text{font-family:FC,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
            "font-variant-ligatures:none}"
        )
        if STATIC:
            return faces + base
        motion = (
            ".rise{animation:rise .7s cubic-bezier(.2,.7,.2,1) both}"
            "@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}"
            ".fade{animation:fade .5s ease-out both}"
            "@keyframes fade{from{opacity:0}to{opacity:1}}"
            ".draw{stroke-dasharray:1;animation:draw 1.8s cubic-bezier(.3,.6,.2,1) both}"
            "@keyframes draw{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}"
            ".grow{transform-box:fill-box;transform-origin:50% 100%;animation:grow .8s cubic-bezier(.2,.7,.2,1) both}"
            "@keyframes grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}"
            ".growx{transform-box:fill-box;transform-origin:0 50%;animation:growx .6s cubic-bezier(.2,.7,.2,1) both}"
            "@keyframes growx{from{transform:scaleX(0)}to{transform:scaleX(1)}}"
            ".blink{animation:blink 1.1s steps(1) infinite}"
            "@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}"
            ".s{display:none}"
            "@media (prefers-reduced-motion:reduce){"
            "*{animation:none!important}.a{display:none}.s{display:inline}}"
        )
        return faces + base + motion

    def write(self) -> Path:
        OUT.mkdir(exist_ok=True)
        bg = (
            f'<rect x=".5" y=".5" width="{self.w - 1}" height="{self.h - 1}" rx="14" '
            f'fill="{BG}" stroke="{LINE}"/>'
        )
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
            f'width="{self.w}" height="{self.h}" role="img" aria-label="{esc(self.title)}">'
            f"<title>{esc(self.title)}</title>"
            f"<defs><style>{self.css()}</style>{''.join(self.defs)}</defs>"
            f"{bg}{''.join(self.body)}</svg>"
        )
        path = OUT / f"{self.name}.svg"
        path.write_text(svg, encoding="utf-8")
        return path


def dual(animated: str, final: str) -> str:
    """SMIL ignores prefers-reduced-motion, so animated SMIL content lives in .a and a
    static copy in .s; the media query in the card's CSS swaps them."""
    if STATIC:
        return final
    return f'<g class="a">{animated}</g><g class="s">{final}</g>'


# ───────────────────────────── cards ─────────────────────────────
def card_hero(data: dict, portrait: str | None) -> Path:
    c = Card("hero", 800, 232, f"{NAME}. " + "; ".join(TAGLINES), T_HERO)
    days = data["days"]

    # name
    c.add(c.rise(c.t(28, 76, NAME, 44, 700), T_HERO + 0.15))

    # role typewriter (SMIL): types each line, holds, erases, loops. Monospace, so widths are exact.
    size, x0, y = 18, 28, 114
    cw = ADV * size
    FR = 0.04  # seconds per frame
    frames: list[tuple[int, int]] = []
    for pi, ph in enumerate(TAGLINES):
        n_ = len(ph)
        frames += [(pi, k) for k in range(1, n_ + 1)]
        frames += [(pi, n_)] * (100 if pi == len(TAGLINES) - 1 else 40)
        frames += [(pi, k) for k in range(n_ - 2, 0, -2)] + [(pi, 0)] * 6
    total = len(frames) * FR
    t0 = T_HERO + 0.7
    smil = f'calcMode="discrete" dur="{total:.2f}s" begin="{t0:.2f}s" repeatCount="indefinite"'
    texts, ids = "", []
    for pi, ph in enumerate(TAGLINES):
        vals = ";".join(f"{(k * cw if p == pi else 0):g}" for p, k in frames)
        c.defs.append(
            f'<clipPath id="tw{pi}"><rect x="{x0}" y="{y - 19}" width="0" height="28">'
            f'<animate attributeName="width" values="{vals}" {smil}/></rect></clipPath>'
        )
        texts += f'<g clip-path="url(#tw{pi})">{c.t(x0, y, ph, size, 400, MUTED)}</g>'
    vals_x = ";".join(f"{x0 + k * cw:g}" for _, k in frames)
    cursor_h = 22
    anim = (
        texts
        + f'<rect x="{x0}" y="{y - 16}" width="{cw * 0.8:.2f}" height="{cursor_h}" fill="{ACCENT}">'
        f'<animate attributeName="x" values="{vals_x}" {smil}/></rect>'
    )
    n = len(TAGLINE)
    final = (
        f"{c.t(x0, y, TAGLINE, size, 400, MUTED)}"
        f'<rect x="{x0 + n * cw:.2f}" y="{y - 16}" width="{cw * 0.8:.2f}" height="{cursor_h}" fill="{ACCENT}"/>'
    )
    if STATIC:
        c.add(final)
    else:
        c.add(f'<g class="fade" style="animation-delay:{t0 - 0.1:.2f}s">{dual(anim, final)}</g>')

    # portrait (optional)
    if portrait:
        cx, cy, r = 706, 70, 52
        c.defs.append(f'<clipPath id="pc"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath>')
        ring_cls = "" if STATIC else ' class="draw"'
        ring_style = "" if STATIC else f' style="animation-delay:{T_HERO + 0.3:.2f}s"'
        c.add(
            c.rise(
                f'<image href="{portrait}" x="{cx - r}" y="{cy - r}" width="{2 * r}" height="{2 * r}" '
                f'clip-path="url(#pc)" preserveAspectRatio="xMidYMid slice"/>',
                T_HERO + 0.2,
            ),
            f'<circle cx="{cx}" cy="{cy}" r="{r + 5}" fill="none" stroke="{ACCENT}" stroke-width="2" '
            f'pathLength="1"{ring_cls}{ring_style} transform="rotate(-90 {cx} {cy})"/>',
        )

    # telemetry trace: the last 140 days of contributions, drawn left to right
    win = [cnt for _, cnt in days[-140:]]
    sm = [sum(win[max(0, i - 1) : i + 2]) / len(win[max(0, i - 1) : i + 2]) for i in range(len(win))]
    vmax = max(sm) or 1
    x_a, x_b, base_y, amp = 28, 772, 196, 56
    pts = [
        (x_a + i * (x_b - x_a) / max(1, len(sm) - 1), base_y - math.sqrt(v / vmax) * amp)
        for i, v in enumerate(sm)
    ]
    line = "M" + " L".join(f"{x:.1f} {yy:.1f}" for x, yy in pts)
    area = f"{line} L{x_b} {base_y} L{x_a} {base_y} Z"
    dcls = "" if STATIC else ' class="draw"'
    dsty = "" if STATIC else f' style="animation-delay:{T_HERO + 1.0:.2f}s"'
    c.add(
        f'<line x1="{x_a}" y1="{base_y}" x2="{x_b}" y2="{base_y}" stroke="{LINE}"/>',
        c.rise(f'<path d="{area}" fill="{ACCENT}" fill-opacity=".10"/>', T_HERO + 1.9),
        f'<path d="{line}" fill="none" stroke="{ACCENT}" stroke-width="1.75" stroke-linejoin="round" '
        f'stroke-linecap="round" pathLength="1"{dcls}{dsty}/>',
        c.rise(c.t(28, 220, "contributions, last 140 days", 11, 400, MUTED), T_HERO + 1.2),
    )

    # refreshed stamp with a pulsing dot (SMIL, swapped for a still dot under reduced motion)
    stamp = f"updated {data['updated']}"
    c.chars[400].update(stamp)
    tw = len(stamp) * ADV * 11
    dot_x = 772 - tw - 12
    dot_anim = (
        f'<circle cx="{dot_x:.1f}" cy="216" r="3" fill="{ACCENT}">'
        '<animate attributeName="r" values="3;5;3" dur="2.4s" repeatCount="indefinite"/>'
        '<animate attributeName="opacity" values="1;.35;1" dur="2.4s" repeatCount="indefinite"/></circle>'
    )
    dot_final = f'<circle cx="{dot_x:.1f}" cy="216" r="3" fill="{ACCENT}"/>'
    c.add(
        c.rise(dual(dot_anim, dot_final) + c.t(772, 220, stamp, 11, 400, MUTED, "end"), T_HERO + 1.4)
    )
    return c.write()


def card_tile(i: int, tile: dict) -> Path:
    base = T_TILES + (i - 1) * T_TILE_GAP
    c = Card(f"tile-{i}", 264, 160, f"{tile['title']}: {tile['text']}", base)
    tc = tile.get("color", ACCENT)
    mark = f'<rect x="20" y="24" width="24" height="3" rx="1.5" fill="{tc}"'
    mark += "/>" if STATIC else f' class="growx" style="animation-delay:{base:.2f}s"/>'
    c.add(mark)
    c.add(c.rise(c.t(20, 56, tile["title"], 16, 700), base + 0.1))
    per_line = int((264 - 40) / (ADV * 12))
    lines = wrap(tile["text"], per_line, 3)
    c.add(
        c.rise(
            "".join(c.t(20, 80 + k * 17, ln, 12, 400, MUTED) for k, ln in enumerate(lines)),
            base + 0.2,
        )
    )
    c.add(
        f'<line x1="20" y1="126" x2="244" y2="126" stroke="{LINE}"/>',
        c.rise(c.t(20, 145, tile["where"], 11, 400, tc), base + 0.3),
    )
    return c.write()


def card_chart(data: dict, st: dict) -> Path:
    months = monthly(data["days"])
    total = sum(v for _, _, v in months)
    c = Card(
        "contributions", 800, 300,
        f"Contributions per month: {fmt_int(total)} in the last 12 months", T_CHART,
    )
    first, last = months[0], months[-1]
    c.add(c.rise(c.t(28, 38, "Contributions per month", 15, 700)))
    c.add(
        c.rise(
            c.t(28, 58, f"{fmt_int(total)} since {MONTHS[first[1] - 1]} {first[0]}", 12, 400, MUTED)
        )
    )

    x0, x1, y_top, y_base = 76, 540, 84, 250
    top = nice_max(max(v for _, _, v in months))
    for frac in (0, 0.5, 1):
        yy = y_base - frac * (y_base - y_top)
        dash = "" if frac == 0 else ' stroke-dasharray="2 4"'
        c.add(
            f'<line x1="{x0}" y1="{yy:g}" x2="{x1}" y2="{yy:g}" stroke="{LINE}"'
            f'{dash}/>',
            c.t(64, yy + 4, fmt_int(int(top * frac)), 11, 400, MUTED, "end"),
        )
    slot = (x1 - x0) / 12
    bw = 22
    peak = max(range(12), key=lambda k: months[k][2])
    for k, (yr, mo, v) in enumerate(months):
        bx = x0 + k * slot + (slot - bw) / 2
        h = max(2.0, v / top * (y_base - y_top)) if v else 2.0
        col = ACCENT if k == peak else mix(BG, ACCENT, 0.55)
        if v == 0:
            col = LINE
        rect = f'<rect x="{bx:.1f}" y="{y_base - h:.1f}" width="{bw}" height="{h:.1f}" rx="3" fill="{col}"'
        d = T_CHART + 0.35 + k * 0.05
        rect += "/>" if STATIC else f' class="grow" style="animation-delay:{d:.2f}s"/>'
        label = c.t(
            bx + bw / 2, y_base - h - 6, fmt_int(v), 11,
            700 if k == peak else 400, TEXT if k == peak else MUTED, "middle",
        )
        c.add(rect, c.rise(label, d + 0.45))
        c.add(c.rise(c.t(bx + bw / 2, 272, MONTHS[mo - 1], 11, 400, MUTED, "middle"), T_CHART + 0.3))

    # stats column
    c.add(f'<line x1="556" y1="28" x2="556" y2="272" stroke="{LINE}"/>')
    cur_label = f"{st['current']} day" + ("" if st["current"] == 1 else "s")
    lon_label = f"longest {st['longest']} day" + ("" if st["longest"] == 1 else "s")
    bd, bc = st["busiest"]
    rows = [
        ("Current streak", cur_label, lon_label, ACCENT),
        ("Active days", fmt_int(st["active"]), f"of {fmt_int(len(data['days']))} days", TEXT),
        ("Busiest day", fmt_int(bc), f"contributions on {fmt_date(bd)}", TEXT),
    ]
    for k, (lab, val, sub, colr) in enumerate(rows):
        y0 = 62 + k * 84
        c.add(
            c.rise(
                c.t(572, y0, lab, 12, 400, MUTED)
                + c.t(572, y0 + 32, val, 30, 700, colr)
                + c.t(572, y0 + 54, sub, 11, 400, MUTED),
                T_CHART + 0.9 + k * 0.15,
            )
        )
    return c.write()


def card_repo(i: int, repo: dict) -> Path:
    base = T_REPOS + i * T_REPO_GAP
    slug = "".join(ch if ch.isalnum() else "-" for ch in repo["name"].lower()).strip("-")
    c = Card(f"repo-{slug}", 800, 132, f"{repo['name']}: {repo.get('description') or 'repository'}", base)
    bar = f'<rect x="0" y="22" width="4" height="88" rx="2" fill="{ACCENT}"'
    bar += "/>" if STATIC else f' class="grow" style="animation-delay:{base:.2f}s"/>'
    c.add(bar)
    c.add(c.rise(c.t(28, 40, repo["name"], 18, 700), base + 0.1))
    per_line = int(744 / (ADV * 13))
    desc = wrap(repo.get("description") or "No description yet.", per_line, 2)
    c.add(
        c.rise(
            "".join(c.t(28, 66 + k * 19, ln, 13, 400, MUTED) for k, ln in enumerate(desc)),
            base + 0.2,
        )
    )
    # meta row: language, stars, forks
    x = 28
    parts = []
    if repo.get("language"):
        colr = repo.get("color") or ACCENT
        parts.append(f'<circle cx="{x + 5}" cy="108" r="5" fill="{colr}"/>')
        parts.append(c.t(x + 18, 112, repo["language"], 12, 400, MUTED))
        x += 18 + len(repo["language"]) * ADV * 12 + 24
    star = (
        f'<path transform="translate({x} 98)" fill="{MUTED}" d="M7 0l2.1 4.6 5 .6-3.7 3.4 1 5L7 11.1 2.6 13.6l1-5L0 5.2l5-.6z"/>'
    )
    parts += [star, c.t(x + 20, 112, fmt_int(int(repo.get("stars", 0))), 12, 400, MUTED)]
    x += 20 + len(fmt_int(int(repo.get("stars", 0)))) * ADV * 12 + 24
    fork = (
        f'<g transform="translate({x} 98)" fill="none" stroke="{MUTED}" stroke-width="1.5">'
        '<circle cx="3" cy="2.5" r="2"/><circle cx="11" cy="2.5" r="2"/><circle cx="7" cy="12" r="2"/>'
        '<path d="M3 4.5v1.5q0 2 2 2h4q2 0 2-2V4.5M7 8v2"/></g>'
    )
    parts += [fork, c.t(x + 20, 112, fmt_int(int(repo.get("forks", 0))), 12, 400, MUTED)]
    c.add(c.rise("".join(parts), base + 0.3))
    where = repo["url"].replace("https://", "")
    c.add(c.rise(c.t(772, 112, where, 12, 400, ACCENT, "end"), base + 0.35))
    return c.write()


def card_graph(data: dict, st: dict) -> Path:
    days = data["days"]
    first, last = days[0][0], days[-1][0]
    start = first - dt.timedelta(days=(first.weekday() + 1) % 7)  # Sunday on/before first day
    ncols = (last - start).days // 7 + 1
    base = T_REPOS + len(data["repos"]) * T_REPO_GAP + 0.2
    c = Card(
        "graph", 800, 212,
        f"Contribution graph: {fmt_int(st['total'])} contributions since {MONTHS[first.month - 1]} {first.year}",
        base,
    )
    c.add(c.rise(c.t(28, 36, "Contribution graph", 15, 700)))
    c.add(
        c.rise(
            c.t(772, 36, f"{fmt_int(st['total'])} since {MONTHS[first.month - 1]} {first.year}", 12, 400, MUTED, "end")
        )
    )

    gx, gy = 56, 74
    pitch = min(16.0, (772 - gx) / ncols)
    cell = pitch - 3
    nz = sorted(cnt for _, cnt in days if cnt > 0)
    q = [nz[int(len(nz) * f)] for f in (0.25, 0.5, 0.75)] if nz else [0, 0, 0]
    shades = [PANEL] + [mix(BG, ACCENT, t) for t in (0.3, 0.52, 0.76, 1.0)]

    def level(cnt: int) -> int:
        return 0 if cnt == 0 else 1 + (cnt > q[0]) + (cnt > q[1]) + (cnt > q[2])

    cols: dict[int, list[str]] = {}
    month_marks: list[tuple[int, int]] = []
    for d, cnt in days:
        col, row = (d - start).days // 7, (d.weekday() + 1) % 7
        cols.setdefault(col, []).append(
            f'<rect x="{gx + col * pitch:.1f}" y="{gy + row * pitch:.1f}" width="{cell:.1f}" '
            f'height="{cell:.1f}" rx="2.5" fill="{shades[level(cnt)]}"/>'
        )
        if d.day == 1 and (not month_marks or col - month_marks[-1][0] >= 3):
            month_marks.append((col, d.month))
    for col in sorted(cols):
        g = "".join(cols[col])
        if STATIC:
            c.add(g)
        else:
            c.add(f'<g class="fade" style="animation-delay:{base + 0.2 + col * 0.014:.2f}s">{g}</g>')
    for col, mo in month_marks:
        c.add(c.rise(c.t(gx + col * pitch, 62, MONTHS[mo - 1], 11, 400, MUTED), base + 0.1))
    for row, lab in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        c.add(c.rise(c.t(28, gy + row * pitch + cell - 1, lab, 10, 400, MUTED), base + 0.1))

    # legend
    ly = 188
    boxes_x = 772 - 5 * (cell + 3) - 4 * ADV * 11 - 6  # left edge of the 5 boxes
    leg = c.t(boxes_x - 6, ly + 9, "Less", 11, 400, MUTED, "end")
    for k, shade in enumerate(shades):
        leg += (
            f'<rect x="{boxes_x + k * (cell + 3):.1f}" y="{ly}" width="{cell:.1f}" '
            f'height="{cell:.1f}" rx="2.5" fill="{shade}"/>'
        )
    leg += c.t(772, ly + 9, "More", 11, 400, MUTED, "end")
    c.add(c.rise(leg, base + 0.4))
    return c.write()


def card_products() -> Path:
    base = T_PRODUCTS
    n = len(PRODUCTS)
    h = 112 + n * 38
    c = Card("products", 800, h, "Wired Minds products and their status", base)
    c.add(c.rise(c.t(28, 38, "Wired Minds products", 15, 700)))
    c.add(c.rise(c.t(28, 58, "Intelligent farming systems. Built from zero. Documented in every commit.", 12, 400, MUTED)))
    head_y = 92
    c.add(
        c.rise(
            c.t(28, head_y, "Product", 11, 400, MUTED)
            + c.t(300, head_y, "Status", 11, 400, MUTED)
            + c.t(440, head_y, "Stack", 11, 400, MUTED)
        ),
        f'<line x1="28" y1="{head_y + 10}" x2="772" y2="{head_y + 10}" stroke="{LINE}"/>',
    )
    for i, (name, label, kind, stack) in enumerate(PRODUCTS):
        y = head_y + 38 + i * 38 - 8
        if kind == "live":
            dot = f'<circle cx="305" cy="{y - 4}" r="4.5" fill="{ACCENT}"/>'
        elif kind == "building":
            dot = f'<circle cx="305" cy="{y - 4}" r="3.8" fill="none" stroke="{ACCENT}" stroke-width="1.8"/>'
        else:
            dot = f'<circle cx="305" cy="{y - 4}" r="3.8" fill="none" stroke="{MUTED}" stroke-width="1.5"/>'
        row = (
            c.t(28, y, name, 13, 700)
            + dot
            + c.t(318, y, label, 12, 400, TEXT if kind != "upcoming" else MUTED)
            + c.t(440, y, stack, 12, 400, MUTED)
        )
        if i < n - 1:
            row += f'<line x1="28" y1="{y + 14}" x2="772" y2="{y + 14}" stroke="{LINE}" stroke-opacity=".5"/>'
        c.add(c.rise(row, base + 0.3 + i * 0.1))
    return c.write()


def card_roles() -> Path:
    base = T_ROLES
    scope_chars = int((760 - 390) / (ADV * 12))
    rows = [(r, o, wrap(sc, scope_chars, 2)) for r, o, sc in ROLES]
    note = wrap(ROLES_NOTE, int(730 / (ADV * 12)), 3)
    heights = [24 + 16 * len(ln) for _, _, ln in rows]
    h = 98 + sum(heights) + 16 * len(note)
    c = Card("roles", 800, int(h), "Official roles and credentials", base)
    c.add(c.rise(c.t(28, 38, "Official roles & credentials", 15, 700)))
    y = 66
    c.add(f'<line x1="28" y1="{y}" x2="772" y2="{y}" stroke="{LINE}"/>')
    for i, ((role, org, lines), rh) in enumerate(zip(rows, heights)):
        top = y
        by = top + 26
        org_col = AMBER if org == "Rogue Engineers" else TEXT
        row = (
            c.t(28, by, role, 13, 700)
            + c.t(190, by, org, 13, 400, org_col)
            + "".join(c.t(390, by + k * 16 - 1, ln, 12, 400, MUTED) for k, ln in enumerate(lines))
        )
        y += rh
        row += f'<line x1="28" y1="{y}" x2="772" y2="{y}" stroke="{LINE}" stroke-opacity=".5"/>'
        c.add(c.rise(row, base + 0.2 + i * 0.1))
    c.add(
        c.rise(
            "".join(c.t(28, y + 26 + k * 16, ln, 12, 400, MUTED) for k, ln in enumerate(note)),
            base + 1.0,
        )
    )
    return c.write()


def card_mission(base: float) -> Path:
    done = sum(1 for d, _ in MISSION if d)
    h = 96 + len(MISSION) * 28
    c = Card("mission", 800, h, f"2026 mission: {done} of {len(MISSION)} done", base)
    c.add(c.rise(c.t(28, 38, "2026 mission", 15, 700)))
    c.add(c.rise(c.t(772, 38, f"{done} of {len(MISSION)} done", 12, 400, MUTED, "end")))
    c.add(c.rise(c.t(28, 58, MISSION_NOTE, 12, 400, MUTED)))
    for i, (ok, text) in enumerate(MISSION):
        y = 94 + i * 28
        if ok:
            box = (
                f'<rect x="28" y="{y - 12}" width="15" height="15" rx="3.5" fill="{ACCENT}"/>'
                f'<path d="M31.5 {y - 4.5}l3.2 3.2 5.6-6.4" fill="none" stroke="{BG}" stroke-width="2" '
                'stroke-linecap="round" stroke-linejoin="round"/>'
            )
        else:
            box = (
                f'<rect x="28.75" y="{y - 11.25}" width="13.5" height="13.5" rx="3" fill="none" '
                f'stroke="{MUTED}" stroke-width="1.5"/>'
            )
        c.add(c.rise(box + c.t(56, y, text, 13, 400, TEXT), base + 0.2 + i * 0.1))
    return c.write()


def chip_rows(c: Card, items: list[str], x: float, y: float, max_x: float, border: str = LINE,
              at: float = 0.0, size: int = 12) -> float:
    """Lay pill chips out left to right, wrapping at max_x. Returns the bottom y of the last row."""
    ch, gap = 26, 8
    cx, cy = x, y
    for i, it in enumerate(items):
        w = len(it) * ADV * size + 22
        if cx + w > max_x and cx > x:
            cx, cy = x, cy + ch + gap
        g = (
            f'<rect x="{cx:.1f}" y="{cy:g}" width="{w:.1f}" height="{ch}" rx="13" fill="{PANEL}" '
            f'stroke="{border}"/>' + c.t(cx + w / 2, cy + 17, it, size, 400, TEXT, "middle")
        )
        c.add(c.rise(g, at + i * 0.05))
        cx += w + gap
    return cy + ch


def side_bar(c: Card, colour: str, base: float) -> str:
    bar = f'<rect x="0" y="22" width="4" height="{c.h - 44}" rx="2" fill="{colour}"'
    return bar + ("/>" if STATIC else f' class="grow" style="animation-delay:{base:.2f}s"/>')


def card_rogue() -> Path:
    base = T_ROGUE
    c = Card("rogue", 800, 0, "Rogue Engineers: robotics education from absolute zero", base)
    c.add(c.rise(c.t(28, 38, "Rogue Engineers", 15, 700)))
    c.add(c.rise(c.t(28, 58, ROGUE_QUOTE, 12, 400, AMBER)))
    lines = wrap(ROGUE_TEXT, int(730 / (ADV * 13)), 6)
    c.add(
        c.rise("".join(c.t(28, 92 + k * 20, ln, 13, 400, MUTED) for k, ln in enumerate(lines)), base + 0.2)
    )
    y = 92 + 20 * len(lines) + 10
    c.add(c.rise(c.t(28, y + 6, "What I teach", 11, 400, MUTED), base + 0.4))
    bottom = chip_rows(c, ROGUE_TEACH, 28, y + 20, 772, AMBER, base + 0.5)
    c.h = int(bottom + 28)
    c.body.insert(0, side_bar(c, AMBER, base))
    return c.write()


def card_security() -> Path:
    base = T_SECURITY
    c = Card("security", 800, 0, "Bug bounty and security research", base)
    c.add(c.rise(c.t(28, 38, "Bug bounty & security research", 15, 700)))
    lines = wrap(SECURITY_TEXT, int(730 / (ADV * 13)), 5)
    c.add(
        c.rise("".join(c.t(28, 70 + k * 20, ln, 13, 400, MUTED) for k, ln in enumerate(lines)), base + 0.15)
    )
    y = 70 + 20 * len(lines) + 14
    c.add(c.rise(c.t(28, y, "Focus areas", 11, 400, MUTED), base + 0.3))
    y += 10
    detail_chars = int(458 / (ADV * 12))
    for i, (lead, detail) in enumerate(SECURITY_FOCUS):
        dl = wrap(detail, detail_chars, 2)
        rh = 14 + 16 * len(dl) + 6
        row = c.t(28, y + 22, lead, 13, 700) + "".join(
            c.t(290, y + 22 + k * 16 - 1, ln, 12, 400, MUTED) for k, ln in enumerate(dl)
        )
        row += f'<line x1="28" y1="{y}" x2="772" y2="{y}" stroke="{LINE}" stroke-opacity=".5"/>'
        c.add(c.rise(row, base + 0.4 + i * 0.1))
        y += rh + 6
    y += 14
    c.add(c.rise(c.t(28, y, "Learning path", 11, 400, MUTED), base + 1.0))
    ny = y + 28
    n = len(SECURITY_PATH)
    xs = [28 + 744 / n * (i + 0.5) for i in range(n)]
    dcls = "" if STATIC else ' class="draw"'
    dsty = "" if STATIC else f' style="animation-delay:{base + 1.1:.2f}s"'
    c.add(
        f'<path d="M{xs[0]:.1f} {ny} L{xs[-1]:.1f} {ny}" fill="none" stroke="{ACCENT}" stroke-width="1.5" '
        f'stroke-opacity=".6" pathLength="1"{dcls}{dsty}/>'
    )
    label_chars = int(136 / (ADV * 11))
    bottom = ny
    for i, (cx, step) in enumerate(zip(xs, SECURITY_PATH)):
        ring = (
            f'<circle cx="{cx:.1f}" cy="{ny}" r="10" fill="none" stroke="{ACCENT}" stroke-opacity=".35"/>'
            if i == n - 1
            else ""
        )
        sl = wrap(step, label_chars, 3)
        lab = "".join(c.t(cx, ny + 26 + k * 14, ln, 11, 400, TEXT, "middle") for k, ln in enumerate(sl))
        bottom = max(bottom, ny + 26 + 14 * (len(sl) - 1))
        c.add(c.rise(f'{ring}<circle cx="{cx:.1f}" cy="{ny}" r="5" fill="{ACCENT}"/>' + lab, base + 1.2 + i * 0.12))
    c.h = int(bottom + 30)
    c.body.insert(0, side_bar(c, ACCENT, base))
    return c.write()


def card_tech() -> Path:
    base = T_TECH
    c = Card("tech", 800, 0, "Tech arsenal: languages, robotics, AI, web, security and tools", base)
    c.add(c.rise(c.t(28, 38, "Tech arsenal", 15, 700)))
    y = 62
    for gi, (label, items) in enumerate(TECH):
        c.add(f'<line x1="28" y1="{y}" x2="772" y2="{y}" stroke="{LINE}" stroke-opacity=".5"/>')
        c.add(c.rise(c.t(28, y + 30, label, 12, 400, MUTED), base + 0.1 + gi * 0.12))
        bottom = chip_rows(c, items, 250, y + 12, 772, LINE, base + 0.15 + gi * 0.12)
        y = bottom + 12
    c.h = int(y + 14)
    return c.write()


# ───────────────────────────── preview ─────────────────────────────
def write_preview(repo_files: list[Path]) -> None:
    o = OUT.name
    tiles = "\n".join(
        f'<img src="{o}/tile-{i}.svg" width="32.5%" alt="">' for i in range(1, len(TILES) + 1)
    )

    def one(name: str) -> str:
        return f'<p><img src="{o}/{name}.svg" width="100%" alt=""></p>'

    repos = "\n".join(f'<p><img src="{o}/{p.name}" width="100%" alt=""></p>' for p in repo_files)
    (ROOT / "preview.html").write_text(
        f"""<!doctype html><meta charset="utf-8"><title>cards preview (final frame)</title>
<style>body{{margin:0;background:#0d1117}}main{{width:728px;margin:24px auto}}
p{{margin:0 0 12px}}.row{{margin:0 0 12px;display:flex;justify-content:space-between}}img{{display:block}}</style>
<main>
{one("hero")}
<div class="row">{tiles}</div>
{one("products")}
{one("rogue")}
{one("roles")}
{one("security")}
{one("tech")}
{one("contributions")}
{repos}
{one("graph")}
{one("mission")}
</main>""",
        encoding="utf-8",
    )


# ───────────────────────────── main ─────────────────────────────
def main() -> None:
    global ADV, GLYPHS
    ensure_fonts()
    ADV, GLYPHS = font_metrics()
    data = load_data()
    st = compute_stats(data["days"])
    portrait = load_portrait()
    if OUT.exists():
        for old in OUT.glob("*.svg"):
            old.unlink()

    written = [card_hero(data, portrait)]
    written += [card_tile(i, t) for i, t in enumerate(TILES, 1)]
    written += [card_products(), card_rogue(), card_roles(), card_security(), card_tech(), card_chart(data, st)]
    repo_files = [card_repo(i, r) for i, r in enumerate(data["repos"])]
    written += repo_files
    written.append(card_graph(data, st))
    written.append(card_mission(T_REPOS + len(data["repos"]) * T_REPO_GAP + 1.2))

    if STATIC:
        write_preview(repo_files)
    if not data["repos"]:
        print("note: no featured repos in the data file, so no repo cards were rendered")
    mode = "static (final frame)" if STATIC else "animated"
    print(f"{mode}: {len(written)} cards in {OUT.relative_to(ROOT)}/")
    for p in written:
        print(f"  {p.name:<28}{p.stat().st_size / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
