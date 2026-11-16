"""Callbacks of the BrushCard group, which `build_brush_card.build()` creates.

Every card ends up in one USD stage, so each needs a prim path of its own. Nuke
also names a card's material prim after the node feeding the GeoCard's material
input, so cards whose texture nodes share a name all render the same stroke.
`sync_names()` derives both from the group's name.
"""

from __future__ import annotations

import os
import re
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

COUNT_KNOB = "texture_count"
INDEX_KNOB = "texture_index"
CYCLE_POS_KNOB = "cycle_pos"
MODE_KNOB = "mode"
MODES = ("frame ranges", "cycle")
START_KNOB = "start_frame"
INCREMENT_KNOB = "increment"
SLOT_KNOB = re.compile(r"stroke(\d+)")


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


def _count(group: nuke.Group) -> int:
    return int(group[COUNT_KNOB].value())


def _is_cycle(group: nuke.Group) -> bool:
    return group[MODE_KNOB].value() == "cycle"


def _reads(group: nuke.Group) -> list[nuke.Node | None]:
    """Slot order is the Switch's input order, so node names don't matter."""
    switch = _internal(group, "Switch")
    if switch is None:
        return []
    return [switch.input(i) for i in range(_count(group))]


def _menu_names(found: list[str], current: str) -> list[str]:
    names = found or [PLACEHOLDER]
    # A stroke removed from teh library stays selected, so a saved comp
    # doesn't change.
    if current and current != PLACEHOLDER and current not in names:
        names = names + [current]
    return names


def _rename(node: nuke.Node | None, name: str) -> None:
    if node is not None and node.name() != name:
        node.setName(name)


def set_stroke(group: nuke.Group, i: int) -> None:
    """Point slot i's Read at its chosen stroke."""
    reads = _reads(group)
    read = reads[i - 1] if i <= len(reads) else None
    if read is None:
        return
    path = strokes().get(group[f"stroke{i}"].value())
    if path is not None:
        _knob(read, "file", nuke.File_Knob).fromUserText(path)
        read["before"].setValue("hold")
        read["after"].setValue("hold")
    read["disable"].setValue(False)
    update_expressions(group)


def update_expressions(group: nuke.Group) -> None:
    """Write the texture_index expression. Slots with no file count as hidden (-1).

    The expressions live on the group's own knobs, so bare knob names like
    `first1` refer to the group. `parent.` would point at the root.
    """
    n = _count(group)
    filled = [bool(r is not None and r["file"].value()) for r in _reads(group)]
    expr = "-1"
    if _is_cycle(group):
        group[CYCLE_POS_KNOB].setExpression(
            f"frame < {START_KNOB} ? 0 : "
            f"fmod(floor((frame - {START_KNOB}) / max({INCREMENT_KNOB}, 1)), {max(n, 1)})"
        )
        for j in reversed(range(n)):
            expr = f"{CYCLE_POS_KNOB} == {j} ? {j if filled[j] else -1} : ({expr})"
    else:
        # Built back to front, so the first listed slot wins on overlaps.
        for j in reversed(range(n)):
            if filled[j]:
                expr = f"frame >= first{j + 1} && frame <= last{j + 1} ? {j} : ({expr})"
    group[INDEX_KNOB].setExpression(expr)


def update_visibility(group: nuke.Group) -> None:
    """Nuke doesn't save knob visibility, so on_create calls this again."""
    cycle = _is_cycle(group)
    group[START_KNOB].setVisible(cycle)
    group[INCREMENT_KNOB].setVisible(cycle)
    n = _count(group)
    for i in range(1, n + 1):
        group[f"first{i}"].setVisible(not cycle)
        group[f"last{i}"].setVisible(not cycle)
        group[f"remove{i}"].setVisible(n > 1)


def _default_range(group: nuke.Group, i: int) -> tuple[int, int]:
    """Slot 1 spans the script's range; later slots follow on, the same length."""
    if i == 1:
        return int(nuke.root().firstFrame()), int(nuke.root().lastFrame())
    first = int(group[f"first{i - 1}"].value())
    last = int(group[f"last{i - 1}"].value())
    return last + 1, last + 1 + (last - first)


def add_texture(group: nuke.Group | None = None) -> None:
    group = group or _this_group()
    i = _count(group) + 1
    if i > 1:
        names = _knob(group, "stroke1", nuke.Enumeration_Knob).values()
    else:
        names = _menu_names(list(strokes()), "")

    stroke = nuke.Enumeration_Knob(f"stroke{i}", f"texture {i}", names)
    stroke.setFlag(nuke.STARTLINE)
    group.addKnob(stroke)

    remove = nuke.PyScript_Knob(
        f"remove{i}",
        "Remove",
        f"import brush_card\nbrush_card.remove_texture_later({i})",
    )
    group.addKnob(remove)

    first, last = _default_range(group, i)
    first_knob = nuke.Int_Knob(f"first{i}", "frames")
    first_knob.setValue(first)
    group.addKnob(first_knob)

    last_knob = nuke.Int_Knob(f"last{i}", "to")
    last_knob.setValue(last)
    last_knob.clearFlag(nuke.STARTLINE)
    group.addKnob(last_knob)

    with group:
        read = nuke.nodes.Read(name=f"{group.name()}_Read{i}")
        read.setXYpos(110 * (i - 1), 0)
        switch = _internal(group, "Switch")
        if switch is None:
            raise RuntimeError(f"{group.name()} has no Switch node")
        switch.setInput(i - 1, read)

    group[COUNT_KNOB].setValue(i)
    update_visibility(group)
    set_stroke(group, i)


def remove_texture_later(i: int) -> None:
    """The Remove button can't delete itself while its own script is running."""
    group = _this_group()
    if nuke.GUI:
        nuke.executeInMainThread(remove_texture, args=(group, i))
    else:
        remove_texture(group, i)


def remove_texture(group: nuke.Group, i: int) -> None:
    n = _count(group)
    if n <= 1:
        nuke.message("BrushCard: a card needs at least one texture.")
        return

    # Shift later slots up one, then drop the last slot.
    for j in range(i, n):
        for name in ("stroke", "first", "last"):
            group[f"{name}{j}"].setValue(group[f"{name}{j + 1}"].value())

    reads = _reads(group)
    for name in ("stroke", "remove", "first", "last"):
        group.removeKnob(group[f"{name}{n}"])
    if reads[n - 1] is not None:
        nuke.delete(reads[n - 1])
    group[COUNT_KNOB].setValue(n - 1)

    update_visibility(group)
    for j in range(1, n):
        set_stroke(group, j)


def refresh(group: nuke.Group | None = None) -> None:
    group = group or _this_group()
    found = list(strokes())
    for i in range(1, _count(group) + 1):
        knob = _knob(group, f"stroke{i}", nuke.Enumeration_Knob)
        current = knob.value()
        names = _menu_names(found, current)
        knob.setValues(names)
        knob.setValue(current if current in names else names[0])
        set_stroke(group, i)

    if not found and nuke.GUI:
        nuke.message(
            f"BrushCard: no strokes found in\n{library_dir()}\n\n"
            f"Add {', '.join(STROKE_EXTENSIONS)} files there, or point the "
            f"{LIBRARY_ENV_VAR} environment variable at the stroke library."
        )


def sync_names(group: nuke.Group) -> None:
    card = group.node(CARD_NODE)
    path = f"{PRIM_ROOT}/{group.name()}"
    if card is not None and card["prim_path"].value() != path:
        card["prim_path"].setValue(path)
    _rename(_internal(group, "Premult"), f"{group.name()}_Premult")
    _rename(_internal(group, "Switch"), f"{group.name()}_Switch")
    for i, read in enumerate(_reads(group), start=1):
        _rename(read, f"{group.name()}_Read{i}")


def on_create() -> None:
    """Also runs when the group is pasted or loaded from a script."""
    group = _this_group()
    sync_names(group)
    update_visibility(group)


def on_knob_changed() -> None:
    group = _this_group()
    knob = nuke.thisKnob().name()
    if knob == "name":
        sync_names(group)
    elif knob == MODE_KNOB:
        update_visibility(group)
        update_expressions(group)
    elif knob == "showPanel":
        update_visibility(group)
    elif match := SLOT_KNOB.fullmatch(knob):
        set_stroke(group, int(match.group(1)))
