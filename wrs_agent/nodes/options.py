"""Small field constraints shared by node options."""

from typing import Annotated

from pydantic import BeforeValidator, Field


def _texts(value):
    return tuple(value) if isinstance(value, list) else value


Texts = Annotated[tuple[str, ...], BeforeValidator(_texts)]
Duration = Annotated[float, Field(gt=0, le=30)]
