import json
from pathlib import Path
from typing import Literal, NamedTuple

from json_values import JsonObject, JsonValue
from session_state import read_record, write_record


class Point(NamedTuple):
    x: int


class Indent(NamedTuple):
    depth: int


class Drawing(NamedTuple):
    origin: Point = Point(0)
    marks: tuple[Point | Indent, ...] = ()


def stored_drawing(path: Path, stored: JsonValue) -> Drawing:
    path.write_text(json.dumps(stored))
    with path.open() as state_file:
        return read_record(state_file, Drawing())


def test_reads_back_nested_records_and_unions(tmp_path: Path) -> None:
    drawing = Drawing(Point(3), (Point(1), Indent(2)))
    with (tmp_path / "state").open("w+") as state_file:
        write_record(state_file, drawing)
        assert read_record(state_file, Drawing()) == drawing


def test_a_mismatched_file_reads_as_the_empty_record(tmp_path: Path) -> None:
    stored: JsonObject = {"origin": {"x": "three"}, "marks": []}
    assert stored_drawing(tmp_path / "state", stored) == Drawing()


def test_an_older_record_without_a_defaulted_field_reads_back(tmp_path: Path) -> None:
    stored: JsonObject = {"marks": [{"x": 1}]}
    assert stored_drawing(tmp_path / "state", stored) == Drawing(marks=(Point(1),))


def test_union_members_with_one_field_each_resolve_by_name(tmp_path: Path) -> None:
    stored: JsonObject = {"marks": [{"depth": 4}, {"x": 5}]}
    expected = Drawing(marks=(Indent(4), Point(5)))
    assert stored_drawing(tmp_path / "state", stored) == expected


class Tagged(NamedTuple):
    id: str
    kind: Literal["tagged"] = "tagged"


class Other(NamedTuple):
    id: str
    kind: Literal["other"] = "other"


class Tagging(NamedTuple):
    first: tuple[Tagged | Other, ...] = ()
    second: tuple[Other | Tagged, ...] = ()


def test_tagged_records_keep_their_type_in_either_union_order(tmp_path: Path) -> None:
    tagging = Tagging((Other("1"), Tagged("2")), (Other("1"), Tagged("2")))
    with (tmp_path / "state").open("w+") as state_file:
        write_record(state_file, tagging)
        assert read_record(state_file, Tagging()) == tagging
