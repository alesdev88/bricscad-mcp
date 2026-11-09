"""What the draw and edit tools accept. Angles are degrees here and radians on the wire."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

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
