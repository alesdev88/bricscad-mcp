"""What the draw and edit tools accept. Angles are degrees here and radians on the wire."""

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Number = Annotated[float, Field(allow_inf_nan=False)]
Positive = Annotated[float, Field(allow_inf_nan=False, gt=0)]
Point = Annotated[list[Number], Field(min_length=2, max_length=3)]


def point3(point: list[float]) -> list[float]:
    x, y, *z = point
    return [float(x), float(y), float(z[0]) if z else 0.0]


def line_breaks(text: str) -> str:
    """MTEXT marks a line break with the code \\P."""
    return text.replace("\r\n", "\n").replace("\n", "\\P")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Rotate(Strict):
    angle: Number
    base: Point


class Scale(Strict):
    factor: Positive
    base: Point


class AttributeUpdate(Strict):
    handle: str
    values: Annotated[dict[str, str], Field(min_length=1)]


Point2D = Annotated[list[Number], Field(min_length=2, max_length=2)]


class Shape(Strict):
    layer: str = "0"


class Line(Shape):
    type: Literal["line"]
    start: Point
    end: Point

    def to_wire(self) -> list[Any]:
        return [self.type, self.layer, point3(self.start), point3(self.end)]


class Polyline(Shape):
    type: Literal["polyline"]
    vertices: Annotated[list[Point2D], Field(min_length=2)]
    bulges: list[Number] | None = None
    closed: bool = False
    elevation: Number = 0.0

    @model_validator(mode="after")
    def bulges_match_vertices(self) -> "Polyline":
        if self.bulges is not None and len(self.bulges) != len(self.vertices):
            raise ValueError("bulges needs one value per vertex")
        return self

    def to_wire(self) -> list[Any]:
        vertices = [[float(x), float(y)] for x, y in self.vertices]
        bulges = None if self.bulges is None else [float(bulge) for bulge in self.bulges]
        return [self.type, self.layer, vertices, bulges, self.closed, float(self.elevation)]


class Circle(Shape):
    type: Literal["circle"]
    center: Point
    radius: Positive

    def to_wire(self) -> list[Any]:
        return [self.type, self.layer, point3(self.center), float(self.radius)]


class Arc(Shape):
    type: Literal["arc"]
    center: Point
    radius: Positive
    start_angle: Number
    end_angle: Number

    def to_wire(self) -> list[Any]:
        return [
            self.type, self.layer, point3(self.center), float(self.radius),
            math.radians(self.start_angle), math.radians(self.end_angle),
        ]


class Text(Shape):
    type: Literal["text"]
    position: Point
    text: str
    height: Positive
    rotation: Number = 0.0
    style: str | None = None

    @field_validator("text")
    @classmethod
    def one_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("text holds one line, use mtext for line breaks")
        return value

    def to_wire(self) -> list[Any]:
        return [
            self.type, self.layer, point3(self.position), self.text, float(self.height),
            math.radians(self.rotation), self.style,
        ]


class MText(Shape):
    type: Literal["mtext"]
    position: Point
    text: str
    height: Positive
    width: Annotated[Number, Field(ge=0)] = 0.0
    style: str | None = None

    def to_wire(self) -> list[Any]:
        return [
            self.type, self.layer, point3(self.position), line_breaks(self.text), float(self.height),
            float(self.width), self.style,
        ]


class Dimension(Shape):
    type: Literal["dimension"]
    kind: Literal["linear", "aligned"] = "linear"
    start: Point
    end: Point
    line_point: Point
    rotation: Number = 0.0

    def to_wire(self) -> list[Any]:
        return [
            self.type, self.layer, self.kind, point3(self.start), point3(self.end), point3(self.line_point),
            math.radians(self.rotation),
        ]


class Hatch(Shape):
    type: Literal["hatch"]
    points: Annotated[list[Point2D], Field(min_length=3)]
    pattern: str = "SOLID"
    scale: Positive = 1.0
    angle: Number = 0.0

    def to_wire(self) -> list[Any]:
        points = [[float(x), float(y)] for x, y in self.points]
        return [self.type, self.layer, points, self.pattern, float(self.scale), math.radians(self.angle)]


class Insert(Shape):
    type: Literal["insert"]
    block: str
    position: Point
    scale: Positive = 1.0
    rotation: Number = 0.0
    attributes: dict[str, str] = Field(default_factory=dict)

    @field_validator("block")
    @classmethod
    def named_block(cls, value: str) -> str:
        if not value or value.startswith("*"):
            raise ValueError("give the name of a block defined in the drawing")
        return value

    def to_wire(self) -> list[Any]:
        return [
            self.type, self.layer, self.block, point3(self.position), float(self.scale),
            math.radians(self.rotation), [[tag, value] for tag, value in self.attributes.items()],
        ]


Entity = Annotated[
    Line | Polyline | Circle | Arc | Text | MText | Dimension | Hatch | Insert, Field(discriminator="type")
]
