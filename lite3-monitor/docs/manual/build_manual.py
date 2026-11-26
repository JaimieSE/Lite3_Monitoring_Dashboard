#!/usr/bin/env python3
"""Build the Lite3 Monitor starting manual (PDF) for group8.

    python3 -m pip install reportlab          # docs tooling only, not a bridge dependency
    python3 lite3-monitor/docs/manual/build_manual.py

Writes Lite3_Monitor_Starting_Manual.pdf next to this file. Every command is real,
selectable text in a monospaced font and never wraps, so it can be copied straight
from the PDF into a terminal. Edit the content below, not the PDF.
"""
from __future__ import annotations

import os
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, PageBreak,
                                NextPageTemplate, PageTemplate, Paragraph, Spacer, Table, TableStyle, XPreformatted)
from reportlab.platypus.tableofcontents import TableOfContents

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "Lite3_Monitor_Starting_Manual.pdf")
VERSION = "2026-11-26"

# ----------------------------------------------------------------------------- fonts
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/Library/Fonts", os.path.expanduser("~/Library/Fonts"),
             "C:/Windows/Fonts"]


def _font(name: str) -> str:
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    raise SystemExit(f"Font {name} not found (install DejaVu fonts)")


pdfmetrics.registerFont(TTFont("Sans", _font("DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("Sans-Bold", _font("DejaVuSans-Bold.ttf")))
pdfmetrics.registerFont(TTFont("Sans-Oblique", _font("DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("Mono", _font("DejaVuSansMono.ttf")))
pdfmetrics.registerFont(TTFont("Mono-Bold", _font("DejaVuSansMono-Bold.ttf")))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans-Oblique",
                              boldItalic="Sans-Bold")
pdfmetrics.registerFontFamily("Mono", normal="Mono", bold="Mono-Bold", italic="Mono", boldItalic="Mono-Bold")

# ----------------------------------------------------------------------------- colours
INK = colors.HexColor("#1c2430")
MUTED = colors.HexColor("#5b6675")
LINE = colors.HexColor("#d5dbe3")
CODE_BG = colors.HexColor("#f3f5f8")
ACCENT = colors.HexColor("#1f5fa8")
GOOD_BG, GOOD = colors.HexColor("#e8f5ec"), colors.HexColor("#1e7a3c")
WARN_BG, WARN = colors.HexColor("#fff6e0"), colors.HexColor("#9a6400")
CRIT_BG, CRIT = colors.HexColor("#fdecec"), colors.HexColor("#b3261e")
INFO_BG, INFO = colors.HexColor("#eaf2fb"), ACCENT
TIER_BG = colors.HexColor("#eef1f5")

# ----------------------------------------------------------------------------- styles
PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
TEXT_W = PAGE_W - 2 * MARGIN

S = {
    "body": ParagraphStyle("body", fontName="Sans", fontSize=9.2, leading=12.6, textColor=INK, spaceAfter=4),
    "small": ParagraphStyle("small", fontName="Sans", fontSize=8, leading=10.5, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName="Sans", fontSize=8.2, leading=10.6, textColor=INK),
    "cellh": ParagraphStyle("cellh", fontName="Sans-Bold", fontSize=8.2, leading=10.6, textColor=INK),
    "h1": ParagraphStyle("h1", keepWithNext=1, fontName="Sans-Bold", fontSize=16, leading=20, textColor=ACCENT,
                         spaceBefore=2, spaceAfter=6),
    "h2": ParagraphStyle("h2", keepWithNext=1, fontName="Sans-Bold", fontSize=11.5, leading=15, textColor=INK,
                         spaceBefore=9, spaceAfter=3),
    "h3": ParagraphStyle("h3", keepWithNext=1, fontName="Sans-Bold", fontSize=9.6, leading=13, textColor=INK,
                         spaceBefore=6, spaceAfter=2),
    "tier": ParagraphStyle("tier", fontName="Sans-Bold", fontSize=9, leading=12, textColor=MUTED),
    "title": ParagraphStyle("title", fontName="Sans-Bold", fontSize=26, leading=31, textColor=INK),
    "subtitle": ParagraphStyle("subtitle", fontName="Sans", fontSize=12.5, leading=17, textColor=MUTED),
    "toc1": ParagraphStyle("toc1", fontName="Sans-Bold", fontSize=9.5, leading=14, textColor=INK),
    "toc2": ParagraphStyle("toc2", fontName="Sans", fontSize=8.6, leading=11.5, leftIndent=14, textColor=MUTED),
}
CODE_PT_MAX, CODE_PT_MIN = 8.0, 6.0
CODE_PAD = 6

# ----------------------------------------------------------------------------- document


class ManualDoc(BaseDocTemplate):
    def __init__(self, path: str):
        super().__init__(path, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN + 4,
                         bottomMargin=MARGIN, title="Lite3 Monitor - Starting Manual (group8)",
                         author="group8", subject="Read-only Lite3 monitoring dashboard: start-up, competition, "
                         "manual takeover, Raspberry Pi checks", creator="build_manual.py")
        frame = Frame(MARGIN, MARGIN, TEXT_W, PAGE_H - 2 * MARGIN - 4, id="f", leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate("cover", [frame], onPage=lambda c, d: None),
                               PageTemplate("main", [frame], onPage=self._decorate)])
        self.sec_start: dict = {}

    def _decorate(self, c, d):
        c.saveState()
        c.setStrokeColor(LINE)
        c.setLineWidth(0.6)
        c.line(MARGIN, PAGE_H - MARGIN + 2, PAGE_W - MARGIN, PAGE_H - MARGIN + 2)
        c.setFont("Sans", 7.5)
        c.setFillColor(MUTED)
        c.drawString(MARGIN, PAGE_H - MARGIN + 6, "Lite3 Monitor · Starting Manual · group8")
        starts = [pg for pg in self.sec_start if pg <= d.page]
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN + 6, self.sec_start[max(starts)] if starts else "")
        c.drawString(MARGIN, MARGIN - 10, f"Read-only monitor: stopping it never affects the robot.   v{VERSION}")
        c.drawRightString(PAGE_W - MARGIN, MARGIN - 10, f"Page {d.page}")
        c.restoreState()

    def afterFlowable(self, f):
        lvl = getattr(f, "_toc_level", None)
        if lvl is None:
            return
        text = f._toc_text
        key = f"s{id(f)}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=lvl, closed=lvl > 0)
        self.notify("TOCEntry", (lvl, text, self.page, key))
        if lvl == 0:
            for pg in [k for k, v in self.sec_start.items() if v == text and k != self.page]:
                del self.sec_start[pg]
            self.sec_start[self.page] = text


story: list = []


def P(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def para(text: str, style: str = "body") -> None:
    story.append(P(text, style))


def H1(text: str, new_page: bool = True) -> None:
    if new_page:
        story.append(PageBreak())
    p = P(escape(text), "h1")
    p._toc_level, p._toc_text = 0, text
    story.append(p)


def H2(text: str) -> None:
    story.append(CondPageBreak(110))
    p = P(escape(text), "h2")
    p._toc_level, p._toc_text = 1, text
    story.append(p)


def H3(text: str) -> None:
    story.append(CondPageBreak(90))
    story.append(P(escape(text), "h3"))


def c(text: str) -> str:
    """Inline code inside a paragraph."""
    return f'<font name="Mono" size="8.2" color="#0f3d73">{escape(text)}</font>'


def code(text: str, label: str | None = None) -> None:
    """A copyable command block. Lines are never wrapped: the font shrinks until the longest line fits."""
    lines = text.strip("\n").splitlines()
    longest = max(lines, key=lambda l: pdfmetrics.stringWidth(l, "Mono", 10))
    avail = TEXT_W - 2 * CODE_PAD - 2
    pt = CODE_PT_MAX
    while pt > CODE_PT_MIN and pdfmetrics.stringWidth(longest, "Mono", pt) > avail:
        pt -= 0.25
    if pdfmetrics.stringWidth(longest, "Mono", pt) > avail:
        raise SystemExit(f"Command line too long to fit without wrapping:\n{longest}")
    style = ParagraphStyle("code", fontName="Mono", fontSize=pt, leading=pt * 1.38, textColor=INK)
    pre = XPreformatted(escape("\n".join(lines)), style)
    rows = [[pre]]
    if label:
        rows.insert(0, [P(f'<font color="#5b6675">{escape(label)}</font>', "small")])
    t = Table(rows, colWidths=[TEXT_W])
    ts = [("BACKGROUND", (0, 0), (-1, -1), CODE_BG), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
          ("LEFTPADDING", (0, 0), (-1, -1), CODE_PAD), ("RIGHTPADDING", (0, 0), (-1, -1), CODE_PAD),
          ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
    if label:
        ts += [("TOPPADDING", (0, 1), (-1, 1), 0), ("BOTTOMPADDING", (0, 0), (-1, 0), 1)]
    t.setStyle(TableStyle(ts))
    story.append(KeepTogether([t, Spacer(1, 5)]))


def table(rows, widths, header: bool = True, zebra: bool = True) -> None:
    data = []
    for i, r in enumerate(rows):
        st = "cellh" if header and i == 0 else "cell"
        data.append([x if not isinstance(x, str) else P(x, st) for x in r])
    t = Table(data, colWidths=[w * TEXT_W for w in widths], repeatRows=1 if header else 0)
    ts = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        ts.append(("BACKGROUND", (0, 0), (-1, 0), TIER_BG))
    if zebra:
        for i in range(2 if header else 1, len(rows), 2):
            ts.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fafbfc")))
    t.setStyle(TableStyle(ts))
    story.append(t)
    story.append(Spacer(1, 6))


def callout(kind: str, title: str, text: str) -> None:
    bg, fg, icon = {"good": (GOOD_BG, GOOD, "✔"), "warn": (WARN_BG, WARN, "▲"), "crit": (CRIT_BG, CRIT, "■"),
                    "info": (INFO_BG, INFO, "●")}[kind]
    body = P(f'<font color="{fg.hexval().replace("0x", "#")}"><b>{icon} {escape(title)}</b></font><br/>{text}', "cell")
    t = Table([[body]], colWidths=[TEXT_W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 3, fg),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.append(KeepTogether([t, Spacer(1, 7)]))


def checklist(items, widths=(0.05, 0.95)) -> None:
    rows = [["☐", it] for it in items]
    data = [[P(f'<font size="11">{a}</font>', "cell"), P(b, "cell")] for a, b in rows]
    t = Table(data, colWidths=[w * TEXT_W for w in widths])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                           ("LEFTPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.append(t)
    story.append(Spacer(1, 6))


def steps(items) -> None:
    data = [[P(f"<b>{i}</b>", "cell"), P(t, "cell")] for i, t in enumerate(items, 1)]
    t = Table(data, colWidths=[0.05 * TEXT_W, 0.95 * TEXT_W])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.append(t)
    story.append(Spacer(1, 4))


def tier(text: str) -> None:
    story.append(PageBreak())
    t = Table([[P(escape(text).upper(), "tier")]], colWidths=[TEXT_W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TIER_BG), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(t)
    story.append(Spacer(1, 8))


# Frequently used commands -----------------------------------------------------------
MON = "~/Lite3_Monitoring_Dashboard/lite3-monitor"
NUC = "user@192.168.10.78"
MAC_START_ALL = "cd ~/Lite3_Monitoring_Dashboard/lite3-monitor\n./scripts/mac/start-all.sh"
WIN_START_ALL = ("cd $HOME\\Lite3_Monitoring_Dashboard\\lite3-monitor\n"
                 "powershell -ExecutionPolicy Bypass -File scripts\\windows\\start-all.ps1")
MAC_START_ROBOT = "cd ~/Lite3_Monitoring_Dashboard/lite3-monitor\n./scripts/mac/start-robot.sh"
WIN_START_ROBOT = ("cd $HOME\\Lite3_Monitoring_Dashboard\\lite3-monitor\n"
                   "powershell -ExecutionPolicy Bypass -File scripts\\windows\\start-robot.ps1")
PI_BRANCH = "claude/pi-perception-panels"

# ============================================================================= COVER
story.append(Spacer(1, 40 * mm))
para("Lite3 Monitor", "title")
para("Starting Manual · group8", "subtitle")
story.append(Spacer(1, 6 * mm))
para("Read-only mission-control dashboard for the DEEP Robotics Lite3. It <b>watches</b> the robot "
     "(NUC on domain 8 + Raspberry Pi <i>group8pi</i>); it can never move it, change its settings or stop its "
     "programs.")
story.append(Spacer(1, 4 * mm))
table([["Priority", "Part", "Use it when"],
       ["1", "Competition-day set-up", "Before and during an official or practice competition run"],
       ["2", "Manual takeover: scene understanding", "A person drives the robot to inspect a scene / check what "
        "Claude and the Pi camera see"],
       ["3", "Raspberry Pi bridging checks", "Before every run that uses the Pi camera, and whenever the Pi "
        "panels look wrong"],
       ["4", "Everyday start-up, reading, troubleshooting, shutdown, updating", "Normal test sessions"],
       ["5", "Reference: one-time setup, simulator, history, re-install, safety", "Rarely"]],
      [0.11, 0.42, 0.47])
callout("crit", "If anything looks wrong",
        "Stopping the monitor is always safe: the robot does not depend on it. The dashboard has <b>no</b> stop "
        "button and cannot take control. To stop or take over the robot, use the robot's own controller / "
        "emergency stop.")
callout("info", "Copying commands",
        "Every grey box is plain text and never wraps. Select it, copy, paste into Terminal / PowerShell. "
        f"Replace values in angle brackets such as {c('<pi-ip>')} before pressing Enter.")
para(f"Version {VERSION}. Built from {c('lite3-monitor/docs/manual/build_manual.py')}; edit that file, then "
     "rebuild, instead of editing the PDF.", "small")

# ============================================================================= TOC
story.append(PageBreak())
story.append(P("Contents", "h1"))
toc = TableOfContents()
toc.levelStyles = [S["toc1"], S["toc2"]]
toc.dotsMinLevel = 0
story.append(toc)

# ============================================================================= QUICK CARD
H1("Quick reference card")
para("Print this page and keep it next to the laptop.")
table([["Thing", "Value"],
       ["NUC address / SSH user", f"{c('192.168.10.78')} / {c('user')}  (also in your robot.env)"],
       ["NUC hostname / ROS domain", f"{c('group8')} / {c('8')}"],
       ["Raspberry Pi hostname / address", f"{c('group8pi')} / {c('<pi-ip>')} (stored only in the NUC's "
        f"{c('bridge/config/local.yaml')})"],
       ["Monitor code on NUC and laptops", c(MON)],
       ["Bridge port (NUC, loopback only)", f"{c('8765')}  (alternative {c('8775')} if another program holds 8765)"],
       ["Pi reporter port", c("8766")],
       ["Dashboard", c("http://127.0.0.1:3000")],
       ["tmux sessions", f"{c('monitor')} (bridge on NUC) · {c('pireport')} (reporter on Pi)"],
       ["Leave tmux running", "Ctrl+B, release, then D"]],
      [0.36, 0.64])
H3("Start (everyone; it never starts a second bridge)")
code(MAC_START_ALL, "Mac - Terminal")
code(WIN_START_ALL, "Windows - PowerShell")
para("Type the NUC password when asked (up to twice). Stop: <b>Ctrl+C</b> in that window.")
H3("Green light in 10 seconds")
table([["Where", "Must show"],
       ["Top bar, left", "<b>Robot verified</b> · Lite3 group8 @ group8 · domain 8"],
       ["Top bar, right", "<b>LIVE</b> (green), delay green or amber, <b>REC</b> running, NUC °C below 80"],
       ["Pi pill / Raspberry Pi panel", "Online, no under-voltage, hostname group8pi"],
       ["TF &amp; diagnostics", "Sensor chips IMU · Joints · Odom · Odom2 · Ultrasound all <b>alive</b>"],
       ["System health", "Mostly green; /leg_odom2, /imu/data, /joint_states ≈ 200 Hz"]],
      [0.3, 0.7])

# ============================================================================= 1 COMPETITION
tier("Priority 1")
H1("1. Competition-day set-up", new_page=False)
para("Goal: the monitor is running, verified and recording <i>before</i> the robot starts, every viewer sees "
     "live data, and nothing in the monitor can slow the robot down. The robot's own competition software "
     "(navigation, perception service on the Pi, mission reporter) is started with the team's own procedure; "
     "it is not part of this monitor and the order does not matter.")

H2("1.1 Roles")
table([["Role", "Who", "Does"],
       ["Bridge owner", "One person", "Makes sure the bridge runs on the NUC and the Pi reporter runs on the Pi "
        "(§3). Restarts them if needed. Watches NUC compute and temperatures."],
       ["Driver", "Whoever holds the robot controller", "Drives during manual takeover. Uses the robot's controls, "
        "never the dashboard."],
       ["Spotter", "One viewer next to the driver", "Reads Robot body, Pi sees now, Claude scene checks and "
        "Mission reports aloud during takeover (§2)."],
       ["Recorder", "One laptop", "Its recorded session is the official record of the run; exports it afterwards."],
       ["Other viewers", "Up to 6 dashboards in total", "Watch only. Map stream off unless they need it."]],
      [0.17, 0.25, 0.58])

H2("1.2 The day before / T-60 min (not in the arena)")
checklist([
    "Every laptop: update and build the dashboard (§8). Never do this in the arena: the build takes minutes.",
    "NUC: update the code and restart the bridge with the new code (§8).",
    f"Pi: the code on the Pi is branch {c(PI_BRANCH)} (needed for scene pictures, §3.3).",
    "Every laptop: robot.env filled in (§9.2) and an SSH key installed on the NUC (§9.3). Without a key you are "
    "asked for the password again after every Wi-Fi drop.",
    "Pi power: proper supply, not the NUC's USB-C (5 V / 3 A for Pi 4, 5 A for Pi 5). Under-voltage makes the Pi "
    "slow down or reboot mid-run.",
    "NUC airflow: fan free, not covered. The NUC throttles at high temperature and navigation lags.",
    "Rehearse reading the panels with the simulator: " + c("./scripts/mac/start-sim.sh --profile group8") + " (§10).",
    "Run the full Pi check ladder once (§3.4) with the robot software running. It has not yet been verified on "
    "the live NUC with the perception topics.",
])

H2("1.3 Start sequence (T-15 min, in the arena)")
steps([
    "Robot powered, robot software started by the team (own procedure). The monitor can start before or after.",
    "<b>Bridge owner:</b> run start-all (below). It starts the bridge in tmux on the NUC if it is not running, "
    "waits until it answers, then opens the tunnel and the dashboard.",
    "<b>Bridge owner:</b> make sure the Pi reporter is running (§3.3) and run the short Pi check (§3.5).",
    "<b>Everyone else:</b> run start-all too. It is safe: it uses the running bridge and never starts a second one.",
    "Everyone: green-light check (Quick reference card) plus the competition extras below.",
    "<b>Recorder:</b> just before the run starts press <b>STOP</b>, then <b>Record session</b>, so the session "
    "contains only this run. Write the run name in the session note.",
])
code(MAC_START_ALL, "Mac - Terminal")
code(WIN_START_ALL, "Windows - PowerShell")
H3("Competition extras to check before the start signal")
table([["Panel", "Expected"],
       ["Mission reports", "Header shows the newest run folder (competition-…). \"Nothing reported in this run "
        "yet\" is normal before the first task. \"No mission log configured\" = wrong branch or config on the NUC."],
       ["Claude scene checks", "Panel present. \"No Claude scene checks since the bridge started\" is normal before "
        "the first trigger."],
       ["Pi sees now", "Not greyed out (record younger than 5 s), frame number increasing."],
       ["Pi link", "LIVE, traffic moving, NUC highlighted in \"talking to\"."],
       ["Top bar", "NUC °C below 80, no \"throttling\"; delay green or amber."],
       ["Viewers", "Hover the delay pill: number of connected dashboards ≤ 6."]],
      [0.25, 0.75])

H2("1.4 During the run: what to watch, in order")
table([["#", "Signal", "Meaning / action"],
       ["1", "Red <b>TELEMETRY LOST</b> banner", "The laptop lost contact (usually Wi-Fi). The robot keeps running. "
        "Positions are drawn as <b>LAST KNOWN</b> and are not live. It reconnects by itself; do not restart "
        "anything unless it stays lost for more than ~30 s (then §6)."],
       ["2", "Robot body: tilt", "Warning at 20°, tipping risk at 35°. Call it out to the driver immediately."],
       ["3", "Robot body: ultrasound (front)", "Close &lt; 0.5 m, very close &lt; 0.25 m, \"clear\" = nothing within "
        "4.5 m."],
       ["4", "Commanded vs actual speed", "Commanded (/handle_state) non-zero but robot not moving = stall or slip. "
        "Stall events also appear in the Event log."],
       ["5", "Top bar NUC °C / throttling", "Amber ≥ 80 °C, red ≥ 90 °C. Throttling slows navigation: plan a pause."],
       ["6", "Pi pill / under-voltage", "Pi may reboot. Perception stops until it is back."],
       ["7", "Claude scene checks", "Red card = failed request (error text shown). Amber = room \"unknown\"."],
       ["8", "Mission reports", "Red = rejected by the server (reason shown). Grey = dry run (not sent for score)."],
       ["9", "Event log / Robot log", "Every warning with time. ERRORs from any ROS program also land in the Event "
        "log."]],
      [0.04, 0.27, 0.69])
callout("warn", "Wi-Fi discipline",
        "Each dashboard adds 5-15 kB/s plus map bursts on the robot's Wi-Fi. Viewers who only need numbers switch "
        "<b>Map stream: off</b> (top-left of the map). People who do not need the dashboard close the tab.")

H2("1.5 After the run")
steps([
    "<b>Recorder:</b> press <b>STOP</b>. History tab → open the session → Export <b>JSON</b>, <b>CSV samples</b> "
    "and <b>CSV events</b>. Share the files with the team.",
    "The robot's own mission log stays on the NUC: " + c("~/lite3_ws/log/operator/competition-*/mission_reports.jsonl")
    + ". The monitor only reads it; do not edit it.",
    "Leave the bridge and the Pi reporter running for the next run.",
    "If something went wrong, copy the last ~20 lines of the bridge (tmux) and of your laptop window for the "
    "debrief.",
])

H2("1.6 Contingencies during a competition")
table([["Situation", "Do this"],
       ["Wi-Fi drop", "Nothing. Robot unaffected; dashboard reconnects (password prompt again if no SSH key)."],
       ["Bridge crashed / not answering", "Bridge owner runs start-all again (it restarts the bridge in tmux). "
        "Robot unaffected; the recording has a gap that is marked as not live."],
       ["7th viewer refused", "Limit is 6. Someone closes a tab; the 7th keeps retrying by itself."],
       ["IDENTITY MISMATCH (red)", "Your robot.env does not say group8 / 8, or you reached a different robot. Fix "
        "robot.env; never ignore it."],
       ["NUC 90 °C+ / throttling", "Tell the team; it is a robot decision whether to pause. Give the NUC air."],
       ["Pi offline", "Check power LED and Wi-Fi. Perception panels go grey; everything else keeps working."],
       ["Laptop dies", "Another laptop runs start-all. History of the dead laptop stays on it."]],
      [0.3, 0.7])

# ============================================================================= 2 MANUAL TAKEOVER
tier("Priority 2")
H1("2. Manual takeover: scene understanding", new_page=False)
para("When a person takes manual control to inspect a scene (a room, a QR code, a hazard sign, stairs or a "
     "curtain), the dashboard is the driver's second pair of eyes: it shows what the Pi camera detects, what "
     "Claude concluded about the scene, and what was reported to the scoring server.")
callout("crit", "The dashboard cannot take over",
        "Taking over, driving and handing back are done only with the robot's own controller and the team's "
        "procedure. The dashboard has no buttons that reach the robot or the Pi, and it cannot trigger a scene "
        "check. When to ask Claude is decided by the Pi's perception service.")

H2("2.1 Before taking over")
checklist([
    "Top bar <b>LIVE</b>, delay green or amber. If STALE or LOST, do not rely on the dashboard.",
    "<b>Pi sees now</b> is not greyed out (younger than 5 s).",
    "Robot body: tilt normal, ultrasound reading plausible.",
    "Note the time in the session note (\"takeover 1: kitchen\"), so the run can be found in History later.",
    "Spotter stands where the driver can hear them.",
])

H2("2.2 Panels the spotter reads")
table([["Panel", "Shows", "How to read it"],
       ["Robot overview", "Commanded vs actual linear / lateral / angular speed",
        "Commanded comes from /handle_state (the robot's velocity command, also during manual control). "
        "Commanded &gt; 0 but actual ≈ 0 = stuck or slipping."],
       ["Robot body", "Tilt, front ultrasound, load per leg motor",
        "Tilt warn 20°, tipping risk 35°. Ultrasound close &lt; 0.5 m, very close &lt; 0.25 m."],
       ["Pi sees now", "Latest detection record: objects + confidence, QR text, hazard signs, stairs / curtain, "
        "frame number and age",
        "Greyed = older than 5 s, do not trust. Hazard signs: high_voltage, radioactive, chemical, biological, "
        "flammable, or \"unidentified triangle\". Stairs / curtain: green = confirmed (with distance), amber = "
        "timestamp_mismatch or stale_camera, grey = other."],
       ["Claude scene checks", "One card per request since the bridge started (newest first, last 20): request id, "
        "picture Claude saw, trigger, room, evidence, answer time",
        "Grey <b>pending</b> = waiting for Claude. Green = room named. Amber = room \"unknown\". Red = failed "
        "(error shown). Header: \"N/M rooms named\"."],
       ["Mission reports", "Newest competition run: per task what was sent, server verdict, score",
        "Green accepted, grey dry run (not scored), red rejected + reason. ✔ / ✘ per evaluated field "
        "(e.g. scene_type, pos, label). Top: server score, latest per task."]],
      [0.18, 0.32, 0.5])

H2("2.3 Scene-understanding drill")
steps([
    "Driver points the camera at the scene and stops. Spotter confirms <b>actual speed ≈ 0</b>.",
    "Spotter watches <b>Pi sees now</b>: the frame number increases and the expected objects / QR / signs appear "
    "with their confidence.",
    "If the perception service asks Claude, a new <b>pending</b> card appears in Claude scene checks. Wait for it "
    "to turn green / amber / red; the card shows how long it took.",
    "Check the <b>picture</b> on the card: is that the scene you meant to show? If the room is amber "
    "(\"unknown\"), read the <b>evidence</b> line and give the camera a better view (closer, more of the room).",
    "Check <b>Mission reports</b>: a new row for the task, accepted, ✔ on each field. A red row shows the server's "
    "reason.",
    "Spotter reads the result aloud; driver moves on.",
])

H2("2.4 Handing back to autonomy")
checklist([
    "Robot stationary and posture normal before hand-back (Robot body).",
    "Hand-back with the robot's own procedure.",
    "Spotter confirms the robot moves again under autonomy: commanded and actual both non-zero, no stall event.",
    "Note \"hand-back\" with the time in the session note.",
])

H2("2.5 Things that look wrong but are normal")
table([["You see", "Why"],
       ["scene-1 appears twice", "Request ids restart at scene-1 when the Pi perception service restarts. The "
        "dashboard keeps them apart by capture time."],
       ["Card without a picture", "The Pi reporter runs without --scene-log, or the Pi had not stored that picture. "
        "See §3.3."],
       ["Older checks missing", "Only requests since the bridge started, at most the last 20."],
       ["Position drifts", "Without the map the position is leg odometry (/leg_odom2) in its own frame; it drifts."],
       ["\"POSE STALE\"", "The pose source is older than 1 s. With navigation the TF only updates ~2 Hz."]],
      [0.3, 0.7])

# ============================================================================= 3 PI CHECKS
tier("Priority 3")
H1("3. Raspberry Pi bridging checks", new_page=False)
H2("3.1 What is bridged, and by whom")
code("""Pi (group8pi)                                         NUC (group8)
perception service --ROS domain 8 topics--------------> monitor bridge (subscribes, read-only)
   /group8pi/perception/detections                        -> "Pi sees now"
   /group8pi/perception/scene_events                      -> "Claude scene checks"
pi_reporter :8766  <--GET /stats, /scene_image---------- monitor bridge (only the NUC may ask)
   (CPU, temp, power, traffic, connections, pictures)     -> "Raspberry Pi", "Pi link", pictures
SSH port           <--TCP connect, no login------------- monitor bridge -> online / response time""")
para("Three independent links: (a) the Pi's ROS topics on domain 8, (b) the read-only reporter on port 8766, "
     "(c) plain reachability. The checks below test each one.")

H2("3.2 One-time: tell the bridge where the Pi is (on the NUC)")
para(f"The Pi's address stays out of git, in {c('bridge/config/local.yaml')} on the NUC. If that file already "
     "exists, edit it instead of overwriting it (the command below replaces the whole file).")
code(f"ssh {NUC}\ncat {MON}/bridge/config/local.yaml", "1 - look at the current file first")
code(f"""cat > {MON}/bridge/config/local.yaml <<'EOF'
peers: [{{name: "Raspberry Pi", host: "<pi-ip>", expected_hostname: "group8pi", stats_port: 8766}}]
EOF""", "2 - only if the file does not exist (replace <pi-ip>)")
para("Then restart the bridge (§8.2). Online / offline and response time now work.")

H2("3.3 Start the read-only reporter on the Pi")
para(f"Approved by the team on 2026-11-26. Standard Python only, nothing installed. It answers two GET requests "
     f"({c('/stats')} and {c('/scene_image')}) and only to the address given with {c('--allow-from')} (the NUC). "
     f"Scene pictures need the {c(PI_BRANCH)} branch.")
code(f"""ssh <pi-user>@<pi-ip>
git clone -b {PI_BRANCH} https://github.com/jaimiese/Lite3_Monitoring_Dashboard.git""",
     "Once: get the code on the Pi (skip if the folder exists)")
code(f"""cd ~/Lite3_Monitoring_Dashboard && git fetch origin && git checkout {PI_BRANCH} && git pull""",
     "If the folder already exists: switch to the right branch")
code("""tmux new -s pireport
cd ~/Lite3_Monitoring_Dashboard/lite3-monitor/bridge
python3 -m lite3_bridge.pi_reporter --allow-from 192.168.10.78 --scene-log ~/usb-camera-perception/scene_log""",
     "Every boot of the Pi: start it in tmux, then Ctrl+B, D to leave it running")
para("Good start prints: " + c("lite3 pi reporter (read-only) on 0.0.0.0:8766, allowed: 192.168.10.78") + ". "
     "Without " + c("--scene-log") + " it serves /stats only and scene cards have no pictures. "
     "If a reporter is already running, " + c("tmux attach -t pireport") + " shows it.")

H2("3.4 Check ladder (run in order, stop at the first failure)")
table([["#", "Check", "Pass when", "If it fails"],
       ["C1", "Pi power", "Raspberry Pi panel: no under-voltage now, no throttling",
        "Proper 5 V supply (3 A Pi 4 / 5 A Pi 5), not NUC USB-C"],
       ["C2", "Pi reachable", "Pi pill online with a response time; ping from NUC answers",
        "Pi off, rebooting, or not on the robot Wi-Fi; wrong host in local.yaml"],
       ["C3", "Right device", "Hostname verified as group8pi (no \"wrong device\" event)",
        "Wrong IP in local.yaml (DHCP may have changed it)"],
       ["C4", "Reporter answers", "Pi link panel LIVE with kB/s; curl from NUC returns JSON",
        "Reporter not running (§3.3), wrong --allow-from, or port 8766 blocked"],
       ["C5", "Pi talks to NUC", "Pi link \"talking to\" list shows the NUC highlighted",
        "Network between Pi and NUC; perception service not running"],
       ["C6", "Perception topics on domain 8", "Both /group8pi/perception/* topics listed on the NUC",
        "Pi perception service not running, or the Pi is on another ROS domain"],
       ["C7", "Detections flowing", "Pi sees now not greyed, frame number increasing",
        "Camera / perception service on the Pi (team's software)"],
       ["C8", "Scene pictures", "A Claude scene card shows a picture",
        "Reporter without --scene-log, or wrong branch on the Pi"],
       ["C9", "Mission reports", "Panel header shows the run folder name",
        "No run started yet, or NUC bridge on the wrong branch"]],
      [0.05, 0.17, 0.4, 0.38])
H3("Commands for C2, C4 and C6 (on the NUC)")
code(f"ssh {NUC}\nping -c 3 <pi-ip>", "C2 - reachability")
code("curl -s --max-time 3 http://<pi-ip>:8766/stats | head -c 300; echo", "C4 - reporter (only works from the NUC)")
code("""export ROS_DOMAIN_ID=8
source /opt/ros/humble/setup.bash
ros2 topic list | grep group8pi
ros2 topic echo --once /group8pi/perception/detections""", "C6 - topics (read-only: lists and prints one message)")
callout("info", "curl from your laptop is refused",
        "That is the allow-list working: only the NUC may read the reporter. Always test C4 from the NUC.")

H2("3.5 Short Pi check before each run (30 s)")
checklist(["Pi pill online, no under-voltage (C1-C3).", "Pi link LIVE, NUC highlighted (C4-C5).",
           "Pi sees now fresh (C7)."])

H2("3.6 Pi troubleshooting")
table([["Dashboard says", "Cause / fix"],
       ["No Raspberry Pi configured", "local.yaml on the NUC has no peers entry (§3.2), or the bridge was not "
        "restarted after editing it."],
       ["Pi offline", "Pi crashed, rebooted or lost Wi-Fi. Check its power LED and network; then C2."],
       ["Reporter not answering (Pi online)", "Reporter not running (§3.3), or port 8766 blocked between NUC and Pi."],
       ["Pi under-voltage (red)", "Power supply too weak; very common on NUC USB-C. The Pi may slow down or reboot."],
       ["Wrong device", "The address in local.yaml now belongs to another machine. Find the Pi's new IP and fix it."],
       ["Pi sees now empty or grey", "C6 / C7: perception topics missing or stale on domain 8."],
       ["Scene cards without pictures", "Restart the reporter with --scene-log on branch " + c(PI_BRANCH) + "."]],
      [0.32, 0.68])

# ============================================================================= 4 DAILY START
tier("Priority 4 - everyday use")
H1("4. Everyday start-up", new_page=False)
H2("4.1 The one-command way (recommended)")
code(MAC_START_ALL, "Mac - Terminal")
code(WIN_START_ALL, "Windows - PowerShell")
para("It (1) starts the bridge on the NUC in tmux, or leaves it alone if it already runs, (2) waits until the "
     "bridge answers, (3) opens the tunnel and the dashboard, and rebuilds the dashboard after a git pull. Type the "
     "NUC password when asked (twice). Keep the window open while monitoring. The browser opens "
     + c("http://127.0.0.1:3000") + " (open it yourself if it does not).")

H2("4.2 The manual way (same result, step by step)")
H3("Step 1 - Bridge on the NUC (one person only)")
code(f"ssh {NUC}\ntmux attach -t monitor || tmux new -s monitor")
code(f"""pgrep -af lite3_bridge
echo $ROS_DOMAIN_ID
{MON}/scripts/nuc/start-bridge.sh""", "Inside tmux: a line from pgrep = already running (skip start); domain must print 8")
para("Good start-up looks like:")
code("""hostname=group8 ROS_DOMAIN_ID=8 ...
profile=group8
... subscribed (read-only) /leg_odom2 ...
... read-only audit passed ...: 0 publishers, 0 services, 0 clients
... lite3-monitor bridge ... (ros mode, READ-ONLY) on ws://127.0.0.1:8765/ws""")
para("After that it repeats " + c("read-only audit passed (graph-scan)") + " every few seconds: normal. "
     "Leave it running with <b>Ctrl+B</b>, release, <b>D</b>; you can close the SSH window.")
H3("Step 2 - Dashboard on your laptop (everyone)")
code(MAC_START_ROBOT, "Mac - Terminal")
code(WIN_START_ROBOT, "Windows - PowerShell")
H3("Step 3 - Green-light check")
para("See the Quick reference card. Anything wrong: §6.")

H1("5. Reading the dashboard")
table([["Panel / element", "What it tells you"],
       ["Top bar", "Identity (Robot verified / IDENTITY MISMATCH), link LIVE / STALE / TELEMETRY LOST with age, "
        "delay (hover: one-way delay, clock offset, kB/s, viewers), NUC °C, Robot °C, Pi pill, recording."],
       ["Live position (no map)", "Robot box and trail from /leg_odom2. The map, paths and goal appear by "
        "themselves when navigation publishes them."],
       ["Map stream button", "Turns the map grid off to save Wi-Fi; numbers stay live."],
       ["Robot overview", "x, y, yaw, speeds vs commanded, navigation status, mission / session time."],
       ["Robot body", "Tilt from IMU, front ultrasound, commanded vs actual, load per leg motor."],
       ["TF &amp; diagnostics", "Sensor alive chips. TF \"not used\" is normal without navigation. A red chip = the "
        "robot reports that sensor as dead: check the robot, not the monitor."],
       ["System health", "Every topic: rate vs expected, age, data rate, publisher count (more than one on "
        "single-publisher topics = possibly another robot on domain 8)."],
       ["Temperatures", "NUC hottest sensor (+ Pi) over 1-30 min. Amber ≥ 80 °C, red ≥ 90 °C."],
       ["NUC compute / Data per topic", "CPU per component (camera, LiDAR, domain bridge, navigation, monitor), "
        "memory, disk; data rate per subscribed topic."],
       ["Raspberry Pi / Pi link", "Pi power, temperature, CPU, memory, SD; traffic and connections (§3)."],
       ["Pi sees now / Claude scene checks / Mission reports", "Perception and scoring (§2.2)."],
       ["Robot log / Event log", "ROS warnings and errors (/rosout); all state changes and faults with time."],
       ["LAST KNOWN · Ns ago (dashed)", "Data is not live. Never read it as the current position."]],
      [0.3, 0.7])

H1("6. Troubleshooting")
table([["Symptom", "Cause / fix"],
       ["CONNECTING forever, or TELEMETRY LOST right away", "Bridge not running → start-all or §4.2 Step 1. Or the "
        "tunnel failed: read the [tunnel] lines in your laptop window (wrong password, NUC off, not on the robot "
        "Wi-Fi)."],
       ["A lite3_bridge is ALREADY RUNNING / port 8765 already in use (on the NUC)", "Fine, use it. After a git "
        "pull replace it with the new code: §8.2. If it says the port is used by ANOTHER program, do not stop "
        "that program; follow the printed steps to use port 8775."],
       ["REFUSING TO START: ROS_DOMAIN_ID=0 != expected 8", "Shell without the team environment. In tmux: "
        + c("export ROS_DOMAIN_ID=8") + " (or open a fresh SSH login) and start again."],
       ["REFUSING TO START: hostname … != expected 'group8'", "You are on the wrong computer. Check the IP."],
       ["IDENTITY MISMATCH (red)", "robot.env says another hostname / domain than the bridge. Set "
        + c("EXPECTED_HOSTNAME=group8") + " and " + c("EXPECTED_DOMAIN_ID=8") + "."],
       ["Laptop: bind … 8765: Address already in use; password asked again and again", "Port 8765 on your laptop "
        "is held by an old tunnel or the simulator. Free it with the command below, then start again."],
       ["Robot box does not move", "System health: /leg_odom2 must be green ≈ 200 Hz. If missing, the robot "
        "driver / domain bridge on the NUC is not running (robot side)."],
       ["A sensor chip is red (NOT alive)", "The robot reports that sensor as dead. Check the robot."],
       ["delay amber / orange, spikes", "Busy Wi-Fi. Fewer viewers, Map stream off, move closer to the access point."],
       ["NUC 9x °C red / throttling", "Overheating. Pause, airflow, check the fan; navigation may lag."],
       ["No NUC °C pill", "The NUC exposes no temperature sensors to normal users (rare): "
        + c("ls /sys/class/hwmon")],
       ["Password asked again and again", "Normal after every Wi-Fi drop without an SSH key: §9.3."],
       ["tmux: command not found", "Run the bridge in a normal SSH window and leave it open."],
       ["Dashboard blank / old after an update", "Stop start-robot, rebuild (§8.1), start again."],
       ["Pi problems", "§3.6."]],
      [0.36, 0.64])
code("""pkill -f "8765:127.0.0.1:8765"; pkill -f "lite3_bridge --sim\"""", "Mac - free laptop port 8765")
code("""Get-NetTCPConnection -LocalPort 8765 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }""",
     "Windows - free laptop port 8765")
para("When asking for help, copy the last ~20 lines of the bridge (tmux) and of your laptop window.")

H1("7. Shutting down", new_page=False)
steps([
    "<b>Laptop:</b> Ctrl+C in the window running start-all / start-robot. Closes the tunnel and the dashboard.",
    "<b>NUC bridge</b> (optional, it can stay running for the next session): attach, Ctrl+C, exit.",
    "<b>Pi reporter</b> (optional): " + c("tmux attach -t pireport") + ", Ctrl+C.",
])
code(f"ssh {NUC}\ntmux attach -t monitor", "NUC: then Ctrl+C to stop the bridge, and type exit")
para("Stopping any of them never affects the robot. Recorded sessions stay on your laptop: History → export.")

H1("8. Updating to a newer version")
callout("warn", "Which branch?",
        f"The newest monitor (Pi perception, scene checks, mission reports) is on {c(PI_BRANCH)}. The "
        f"{c('--restart')} option of start-bridge is on {c('claude/gallant-hamilton-q50da3')} only, and "
        f"{c('main')} has neither. Until they are merged, use {c(PI_BRANCH)} on the NUC, the Pi and the laptops, and "
        "use the --restart fallback in §8.2.")
H2("8.1 Laptop")
code(f"""cd ~/Lite3_Monitoring_Dashboard
git fetch origin && git checkout {PI_BRANCH} && git pull
cd lite3-monitor/web && npm ci && npm run build""", "Mac - Terminal / Windows - PowerShell (same commands)")
H2("8.2 NUC (then restart the bridge with the new code)")
code(f"""ssh {NUC}
cd ~/Lite3_Monitoring_Dashboard
git fetch origin && git checkout {PI_BRANCH} && git pull""")
code(f"{MON}/scripts/nuc/start-bridge.sh --restart", "Restart, if your checkout has --restart (run inside tmux monitor)")
code(f"""pkill -f "python.* -m lite3_bridge"
{MON}/scripts/nuc/start-bridge.sh""", "Restart fallback (inside tmux monitor); stops only the monitor bridge")
para(f"Re-run {c('scripts/nuc/install.sh')} only if {c('bridge/requirements.txt')} changed.")

# ============================================================================= REFERENCE
tier("Priority 5 - reference, rarely needed")
H1("9. One-time laptop set-up", new_page=False)
H2("9.1 Install")
code("""brew install node@20 python@3.12
git clone https://github.com/jaimiese/Lite3_Monitoring_Dashboard.git
cd Lite3_Monitoring_Dashboard && git checkout claude/pi-perception-panels
cd lite3-monitor && ./scripts/mac/install.sh""", "Mac - skip what you already have (Node >= 20, Python >= 3.10)")
code("""winget install OpenJS.NodeJS.LTS Python.Python.3.12 Git.Git""", "Windows - then reopen PowerShell")
code("""git clone https://github.com/jaimiese/Lite3_Monitoring_Dashboard.git
cd Lite3_Monitoring_Dashboard; git checkout claude/pi-perception-panels
cd lite3-monitor
powershell -ExecutionPolicy Bypass -File scripts\\windows\\install.ps1""", "Windows - PowerShell")
para("-ExecutionPolicy Bypass applies to that one command only. If Windows Firewall asks about Python or Node, "
     "Cancel is fine: everything listens on 127.0.0.1. Use Chrome or Edge. If ssh is missing: Settings → Apps → "
     "Optional features → OpenSSH Client.")
H2("9.2 robot.env (connection file)")
para(f"Mac: {c('scripts/mac/robot.env')} · Windows: {c('scripts/windows/robot.env')} (created by install). "
     "Git-ignored; never commit it.")
code("""NUC_HOST=192.168.10.78
NUC_USER=user
EXPECTED_HOSTNAME=group8
EXPECTED_DOMAIN_ID=8""")
code(f"ssh {NUC} hostname", "Check: must print group8")
H2("9.3 SSH key (no more password prompts)")
para("This adds your key to the NUC user's ~/.ssh/authorized_keys; agree with the team first.")
code(f"ssh-keygen -t ed25519\nssh-copy-id {NUC}", "Mac")
code("""ssh-keygen -t ed25519
type $env:USERPROFILE\\.ssh\\id_ed25519.pub | ssh user@192.168.10.78 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys\"""",
     "Windows - PowerShell")

H1("10. Practice with the simulator (no robot)", new_page=False)
para("The same dashboard against a simulated robot, including a simulated Pi, scene checks and mission reports. "
     "Good for training spotters.")
code("""cd ~/Lite3_Monitoring_Dashboard/lite3-monitor
./scripts/mac/start-sim.sh --profile group8""", "Mac - behaves like our robot (no map / TF)")
code("""powershell -ExecutionPolicy Bypass -File scripts\\windows\\start-sim.ps1 -Profile group8""", "Windows")
table([["Mac option", "Windows option", "Effect"],
       ["--dropouts", "-Dropouts", "Simulate Wi-Fi loss (TELEMETRY LOST)"],
       ["--latency 150", "-LatencyMs 150", "150 ms one-way delay"],
       ["--no-faults", "-NoFaults", "No injected faults"],
       ["--no-map", "-NoMap", "Bridge never streams the map"],
       ["--dev", "-Dev", "Development server (hot reload)"]],
      [0.25, 0.25, 0.5])

H1("11. Several viewers", new_page=False)
table([["", "Per extra viewer"],
       ["Robot navigation / SLAM / locomotion", "No effect: the bridge subscribes to ROS once however many watch."],
       ["NUC CPU", "Very small: one SSH session plus re-sending the same messages."],
       ["Robot Wi-Fi upload", "≈ 5-15 kB/s telemetry, plus map bursts if the map is on."],
       ["Limit", "6 dashboards (server.max_clients). A 7th keeps retrying."]],
      [0.35, 0.65])
para("Only one person starts the bridge; start-all is safe for everyone because it never starts a second one.")

H1("12. History and export", new_page=False)
para("Recording starts automatically when the page opens. <b>STOP</b> ends a session, <b>Record session</b> starts "
     "the next one. Sessions are saved at 1 Hz on <i>your</i> laptop in " + c("web/data/history") + ". History tab: "
     "details, trajectory, charts, notes, compare up to 4 runs, export JSON / CSV samples / CSV events, delete. "
     "Samples taken while not live store no position.")

H1("13. Re-installing the bridge on the NUC / discovery", new_page=False)
code(f"""cd ~
git clone -b {PI_BRANCH} https://github.com/jaimiese/Lite3_Monitoring_Dashboard.git
{MON}/scripts/nuc/install.sh""", "On the NUC - answer y; installs 4 Python packages into that folder only")
para("No sudo, nothing in lite3_ws. Remove completely: stop the bridge, then "
     + c("rm -rf ~/Lite3_Monitoring_Dashboard") + ".")
para("Re-check which ROS topics exist (read-only, installs nothing on the NUC; writes a report into "
     + c("docs/discovery/") + " on your laptop):")
code("./scripts/mac/discover-remote.sh 8", "Mac - add --heavy to also measure camera / LiDAR data rates once")
code("powershell -ExecutionPolicy Bypass -File scripts\\windows\\discover-remote.ps1", "Windows - add -Heavy")

H1("14. Safety rules (for everyone)", new_page=False)
checklist([
    "The monitor is <b>read-only</b>. Never edit it to publish, call services / actions, or change parameters.",
    "Never change anything in ~/lite3_ws for the monitor.",
    "The bridge listens only on the NUC itself (127.0.0.1); access only through SSH.",
    "The Pi reporter answers only the NUC's address and runs no commands.",
    "Before committing changes: " + c("python3 lite3-monitor/tools/check_readonly.py") + " must pass.",
    "If in doubt: stop the monitor. The robot does not depend on it.",
])

H1("Appendix A. Reference", new_page=False)
table([["Item", "Value"],
       ["Robot profile (NUC)", c("bridge/config/group8.yaml") + " (merged over default.yaml, then local.yaml)"],
       ["Pi perception topics", c("/group8pi/perception/detections") + ", " + c("/group8pi/perception/scene_events")],
       ["Mission log read by the bridge", c("~/lite3_ws/log/operator/competition-*/mission_reports.jsonl")],
       ["Command topic", c("/handle_state") + " (Twist, ~200 Hz)"],
       ["Odometry (pose)", c("/leg_odom2") + " (Odometry, ~200 Hz)"],
       ["Ultrasound", c("/us_publisher/ultrasound_distance") + " (m; 4.5 = clear)"],
       ["Bridge endpoints (GET only)", c("/healthz") + ", " + c("/api/status") + ", " + c("/api/clock") + ", "
        + c("/api/pi/scene_image") + ", WebSockets " + c("/ws") + " and " + c("/ws/map")],
       ["Thresholds", "Tilt 20° / 35° · ultrasound 0.5 / 0.25 m · NUC 80 / 90 °C · Pi detections stale after 5 s · "
        "link STALE after 1.5 s, LOST after 3.5 s"],
       ["Docs in the repo", c("lite3-monitor/docs/") + ": STARTUP_MANUAL.md, TEAM_SETUP.md, SAFETY.md, "
        "ARCHITECTURE.md, PROTOCOL.md, NUC_INTEGRATION.md"]],
      [0.3, 0.7])

H1("Appendix B. Not yet verified (as of this version)", new_page=False)
checklist([
    "Pi perception panels against the live NUC bridge, and in a browser on the team's Mac.",
    "ros2 node info /lite3_monitor_readonly on the robot (should show no publishers) and bridge CPU in top.",
    "Robot temperature topics: none on domain 8 yet, so the Robot °C pill stays empty.",
    "A static map → base_link transform exists on the robot next to the moving one (TF setup on the robot side). "
    "The monitor ignores the static one; whether to remove it is the team's decision.",
])


def main() -> None:
    doc = ManualDoc(OUT)

    def first_page(canvas, d):
        canvas.saveState()
        canvas.setFillColor(ACCENT)
        canvas.rect(0, PAGE_H - 14 * mm, PAGE_W, 14 * mm, stroke=0, fill=1)
        canvas.restoreState()

    doc.pageTemplates[0].onPage = first_page
    story.insert(0, NextPageTemplate("main"))
    doc.multiBuild(story)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
