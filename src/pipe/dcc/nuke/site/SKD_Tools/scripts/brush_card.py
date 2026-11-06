"""Callbacks of the BrushCard group, which `build_brush_card.build()` creates.

Every card ends up in one USD stage, so each needs a prim path of its own. Nuke
also names a card's material prim after the node feeding the GeoCard's material
input, so cards whose texture nodes share a name all render the same stroke.
`sync_names()` derives both from the group's name.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypeVar

import nuke

from pipe.core.util.paths import get_production_path

KnobT = TypeVar("KnobT", bound=nuke.Knob)

LIBRARY_ENV_VAR = "BRUSH_CARD_LIB"
STROKE_EXTENSIONS = (".exr", ".png", ".tif", ".tiff")
PLACEHOLDER = "<no strokes found>"
PRIM_ROOT = "/BrushCards"

CARD_NODE = "Card"


def library_dir() -> Path:
    value = os.environ.get(LIBRARY_ENV_VAR)
    if value:
        return Path(value)
    return get_production_path() / "lighting" / "crepuscular_cards"


def strokes() -> dict[str, str]:
    """{display name: file path} of every stroke in the library."""
    lib = library_dir()
    if not lib.is_dir():
        return {}
    return {
        f.stem: f.as_posix()
        for f in sorted(lib.iterdir())
        if f.is_file() and f.suffix.lower() in STROKE_EXTENSIONS
    }


def _this_group() -> nuke.Group:
    node = nuke.thisNode()
    if not isinstance(node, nuke.Group):
        raise TypeError(f"BrushCard callback ran on {node.Class()} {node.name()!r}")
    return node


def _knob(node: nuke.Node, name: str, kind: type[KnobT]) -> KnobT:
    knob = node[name]
    if not isinstance(knob, kind):
        raise TypeError(
            f"{node.name()}.{name} is {type(knob).__name__}, expected {kind.__name__}"
        )
    return knob


def _internal(group: nuke.Group, node_class: str) -> nuke.Node | None:
    for node in group.nodes():
        if node.Class() == node_class:
            return node
    return None
