from pathlib import Path
from typing import NamedTuple

from session_state import read_record, write_record


class Point(NamedTuple):
    x: int


class Label(NamedTuple):
    text: str
    size: int


class Drawing(NamedTuple):
    origin: Point = Point(0)
    marks: tuple[Point | Label, ...] = ()


def test_reads_back_nested_records_and_unions(tmp_path: Path) -> None:
    drawing = Drawing(Point(3), (Point(1), Label("a", 2)))
    with (tmp_path / "state").open("w+") as state_file:
        write_record(state_file, drawing)
        assert read_record(state_file, Drawing()) == drawing
