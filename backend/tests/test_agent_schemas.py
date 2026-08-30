"""What the model is asked to fill in.

Every agent call declares a Pydantic response schema, which Gemini is given as
a JSON schema and must answer within. That only works for shapes a JSON schema
can actually describe, and one common Python type cannot be described: a
mapping with arbitrary keys.

`dict[str, float]` becomes an object with no declared properties. Gemini
answers it with `{}` — not an error, not a refusal, just an empty object, every
single time. `QuoteExtraction.line_items` was that type, so every live mission
read a supplier's MOQ and lead time correctly and reported no price at all,
then rejected every supplier for "still missing unit_price". The symptom is
several steps from the cause, so this is a class of bug worth failing a test
over rather than finding again.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import BaseModel

from app.agents import schemas as agent_schemas


def response_models() -> list[type[BaseModel]]:
    return [
        obj
        for _, obj in inspect.getmembers(agent_schemas, inspect.isclass)
        if issubclass(obj, BaseModel) and obj is not BaseModel
        and obj.__module__ == agent_schemas.__name__
    ]


def open_maps(node: object, path: str = "") -> list[str]:
    """Find objects that declare no properties but accept arbitrary keys."""
    found: list[str] = []
    if isinstance(node, dict):
        is_object = node.get("type") == "object" or "additionalProperties" in node
        declares_nothing = not node.get("properties") and "$ref" not in node
        allows_anything = node.get("additionalProperties") not in (None, False)
        if is_object and declares_nothing and allows_anything:
            found.append(path or "<root>")
        for key, value in node.items():
            found += open_maps(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += open_maps(value, f"{path}[{index}]")
    return found


@pytest.mark.parametrize("model", response_models(), ids=lambda m: m.__name__)
def test_no_response_schema_asks_for_an_arbitrary_key_mapping(model: type[BaseModel]):
    offenders = open_maps(model.model_json_schema())
    assert not offenders, (
        f"{model.__name__} contains an open-ended object at {offenders}. "
        "Gemini answers those with {} rather than failing. Use a list of typed "
        "entries — see QuoteExtraction.line_items and LineItem."
    )


def test_line_items_survive_the_round_trip_to_the_mapping_the_domain_uses():
    """The domain works in component -> price; the model answers in a list."""
    from app.agents.schemas import LineItem, QuoteExtraction

    extraction = QuoteExtraction(
        currency="IDR",
        line_items=[
            LineItem(component="botol", unit_price=8500.0),
            LineItem(component=" pump ", unit_price=2500.0),
            LineItem(component="", unit_price=99.0),      # dropped: unnamed
        ],
    )
    assert extraction.price_map() == {"botol": 8500.0, "pump": 2500.0}


def test_a_reply_with_no_prices_maps_to_nothing_rather_than_a_zero():
    from app.agents.schemas import QuoteExtraction

    assert QuoteExtraction(not_a_quote=True).price_map() == {}
