"""Validated overlay layout and private, local FFmpeg runtime commands."""

import asyncio
from copy import deepcopy
import re

import zmq
import zmq.asyncio

ELEMENTS = ("title", "source", "date", "clock", "sensor", "ticker", "cta")
ANCHORS = (
    "auto",
    "top_left",
    "top_center",
    "top_right",
    "middle_left",
    "middle_center",
    "middle_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
)
TEXT_DEFAULTS = dict(
    visible=True,
    anchor="auto",
    x=24,
    y=24,
    font_size=28,
    color="#FFFFFF",
    background_color="#000000",
    background_opacity=0,
    shadow=True,
    scroll="off",
    speed=65,
    direction="left",
)
DEFAULT_LAYOUT = {
    "band": dict(
        visible=True, position="bottom", height=108, color="#000000", opacity=45
    ),
    **{key: dict(TEXT_DEFAULTS) for key in ELEMENTS},
}
DEFAULT_LAYOUT["sensor"].update(y=12, scroll="overflow", speed=35)
DEFAULT_LAYOUT["ticker"].update(y=16, scroll="always")
FORMATS = {
    "date": {"iso": "%Y-%m-%d", "day_first": "%d/%m/%Y", "month_first": "%m/%d/%Y"},
    "clock": {"24h_seconds": "%H:%M:%S", "24h": "%H:%M", "12h": "%I:%M %p"},
}
DEFAULT_LAYOUT["date"]["format"] = "iso"
DEFAULT_LAYOUT["clock"]["format"] = "24h_seconds"


def validate_layout(patch, base=None):
    if not isinstance(patch, dict) or patch.keys() - DEFAULT_LAYOUT.keys():
        raise ValueError("Invalid overlay layout")
    result = deepcopy(base or DEFAULT_LAYOUT)
    for name, changes in patch.items():
        allowed = DEFAULT_LAYOUT[name]
        if not isinstance(changes, dict) or changes.keys() - allowed.keys():
            raise ValueError("Invalid overlay element")
        for key, value in changes.items():
            if key in ("visible", "shadow"):
                valid = type(value) is bool
            elif key in ("color", "background_color"):
                valid = isinstance(value, str) and re.fullmatch(
                    r"#[0-9a-fA-F]{6}", value
                )
            elif key == "anchor":
                valid = isinstance(value, str) and value in ANCHORS
            elif key == "position":
                valid = value in ("top", "bottom")
            elif key == "direction":
                valid = value in ("left", "right")
            elif key == "scroll":
                valid = value in ("off", "overflow", "always")
            elif key == "format":
                valid = isinstance(value, str) and value in FORMATS[name]
            else:
                low, high = {
                    "x": (0, 3840),
                    "y": (0, 2160),
                    "font_size": (8, 120),
                    "speed": (0, 400),
                    "height": (40, 400),
                    "opacity": (0, 100),
                    "background_opacity": (0, 100),
                }[key]
                valid = type(value) is int and low <= value <= high
            if not valid:
                raise ValueError("Invalid overlay " + key)
            result[name][key] = value
    return result


def color(value, opacity=100):
    return "0x" + value[1:] + "@" + str(opacity / 100)


def box_options(settings):
    band = settings["overlay_layout"]["band"]
    height = round(band["height"] * settings["height"] / 1080)
    return dict(
        x="0",
        y="0" if band["position"] == "top" else f"ih-{height}",
        w="iw",
        h=str(height),
        color=color(band["color"], band["opacity"] if band["visible"] else 0),
        t="fill",
    )


def text_options(name, settings, overlay, font):
    layout = settings["overlay_layout"]
    element, band = layout[name], layout["band"]
    scale = settings["height"] / 1080
    size = max(8, round(element["font_size"] * scale))
    mx, my = round(element["x"] * scale), round(element["y"] * scale)
    height = round(band["height"] * scale)
    if element["anchor"] == "auto":
        x = str(mx) if name in ("title", "source", "sensor") else f"w-tw-{mx}"
        if name in ("title", "clock", "date"):
            y = str(my + (height if band["position"] == "top" else 0))
        elif name in ("sensor", "ticker"):
            top = "0" if band["position"] == "top" else f"h-{height}"
            y = f"{top}+{my}" if name == "sensor" else f"{top}+{height}-th-{my}"
        else:
            y = (
                f"h-{height}-th-{my}"
                if band["position"] == "bottom"
                else str(height + my)
            )
        if name == "date":
            x += "-" + str(round(layout["clock"]["font_size"] * scale * 5.8))
    else:
        vertical, horizontal = element["anchor"].split("_")
        x = {"left": str(mx), "center": f"(w-tw)/2+{mx}", "right": f"w-tw-{mx}"}[
            horizontal
        ]
        y = {"top": str(my), "middle": f"(h-th)/2+{my}", "bottom": f"h-th-{my}"}[
            vertical
        ]
    speed = round(element["speed"] * scale, 3)
    if element["scroll"] != "off" and speed:
        moving = (
            f"w-mod(t*{speed},w+text_w)"
            if element["direction"] == "left"
            else f"-text_w+mod(t*{speed},w+text_w)"
        )
        x = (
            moving
            if element["scroll"] == "always"
            else f"if(lte(text_w,w-{2*mx}),{x},{moving})"
        )
    return dict(
        fontfile=str(font),
        textfile=str(overlay / (name + ".txt")),
        reload="1",
        expansion="none",
        fontsize=str(size),
        fontcolor=color(element["color"]),
        shadowcolor="black",
        shadowx="1" if element["shadow"] else "0",
        shadowy="1" if element["shadow"] else "0",
        x=x,
        y=y,
        box="1" if element["background_opacity"] else "0",
        boxcolor=color(element["background_color"], element["background_opacity"]),
        boxborderw="6",
    )


def options_string(values, graph=False):
    def escape(value):
        value = str(value).replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        return value.replace(",", "\\,") if graph else value

    return ":".join(key + "=" + escape(value) for key, value in values.items())


def filters(settings, overlay, font, runtime=True):
    endpoint = "ipc://" + str(overlay / "control.sock")
    return (
        ["zmq=bind_address='" + endpoint.replace(":", "\\:") + "'"] if runtime else []
    ) + [
        "drawbox@band=" + options_string(box_options(settings), graph=True),
        *[
            "drawtext@"
            + name
            + "="
            + options_string(text_options(name, settings, overlay, font), graph=True)
            for name in ELEMENTS
        ],
    ]


async def update(settings, overlay, font, previous=None):
    """Send commands over a private Unix socket; never open a TCP listener."""
    socket = zmq.asyncio.Context.instance().socket(zmq.REQ)
    socket.setsockopt(zmq.LINGER, 0)
    socket.connect("ipc://" + str(overlay / "control.sock"))
    try:
        before_box = box_options(previous) if previous else {}
        commands = [
            f"drawbox@band {k} {v}"
            for k, v in box_options(settings).items()
            if k != "t" and before_box.get(k) != v
        ]
        for name in ELEMENTS:
            before = text_options(name, previous, overlay, font) if previous else {}
            commands += [
                f"drawtext@{name} {key} {value}"
                for key, value in text_options(name, settings, overlay, font).items()
                if key
                not in (
                    "fontfile",
                    "textfile",
                    "reload",
                    "expansion",
                    "shadowcolor",
                    "boxborderw",
                )
                and before.get(key) != value
            ]
        for command in commands:
            await socket.send_string(command)
            reply = await asyncio.wait_for(socket.recv_string(), 2)
            if not reply.startswith("0 "):
                raise ValueError("Overlay command rejected: " + " ".join(command.split()[:2]) + " (" + reply.split()[0] + ")")
    finally:
        socket.close()
