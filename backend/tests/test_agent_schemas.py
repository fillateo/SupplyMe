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
from app.agents.communication import sign


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


class TestARequiredFieldMustBeAnswerableFromThePrompt:
    """A schema may only demand what the prompt actually supplies.

    `SelectionNarrative.vendor_id` is required, and for a while the ranking text
    the agent was shown carried only the vendor's *name* — so the sole way to
    satisfy the schema was to invent an id. The handler then matched on that id
    to tell a selection from its runner-up, which is a comparison against a
    guess. This is the same defect as asking for a mapping the model cannot
    express, and it fails quietly in the same way: plausible output, wrong
    provenance.
    """

    def _row(self):
        from app.workflow.handlers import _render_row

        return _render_row(
            {
                "node_key": "glass_bottle",
                "node_name": "Glass bottle",
                "vendor": {"id": "ven_abc123", "name": "PT Example", "city": "Tangerang"},
                "score": {"total": 82.4, "components": []},
                "quote": None,
            }
        )

    def test_the_rendered_ranking_row_carries_the_vendor_id(self):
        assert "vendor_id=ven_abc123" in self._row()

    def test_it_still_carries_the_node_key_the_annotation_is_looked_up_by(self):
        assert "[glass_bottle]" in self._row()

    def test_every_required_field_of_the_narrative_schema_is_present_in_a_row(self):
        """Read the schema, not a remembered list of its fields."""
        from app.agents.schemas import SelectionNarrative

        row = self._row()
        required = [
            name
            for name, field in SelectionNarrative.model_fields.items()
            if field.is_required()
        ]
        assert "vendor_id" in required, "the test is guarding a field that is no longer required"
        # `why` is what the agent writes; the rest it must read off the row.
        for name in (f for f in required if f != "why"):
            token = "[" if name == "node_key" else f"{name}="
            assert token in row, (
                f"SelectionNarrative requires `{name}` but a ranking row contains "
                f"nothing the model could read it from"
            )


# --- Outreach signatures ----------------------------------------------------
# Three of five emails in a live mission went out ending in "[Your Name]" or
# "[My Name]". The instruction now tells the model not to sign, but a prompt is
# a request rather than a guarantee, so the guarantee lives in sign().


@pytest.mark.parametrize(
    "placeholder", ["[Your Name]", "[My Name]", "[Name]", "[Your Company]"]
)
def test_sign_replaces_a_placeholder_with_the_real_name(placeholder: str) -> None:
    body = f"Hello,\n\nWhat is your MOQ?\n\nThank you,\n{placeholder}"
    signed = sign(body, "Dana Reyes")
    assert placeholder not in signed
    assert signed.endswith("Thank you,\nDana Reyes")


def test_sign_adds_a_sign_off_when_the_model_wrote_none() -> None:
    assert sign("Hello,\n\nWhat is your MOQ?", "Dana Reyes") == (
        "Hello,\n\nWhat is your MOQ?\n\nThanks,\nDana Reyes"
    )


def test_sign_without_a_name_leaves_no_dangling_sign_off() -> None:
    """An unsigned email is terse. An invented name is a person who is not real."""
    signed = sign("Hello,\n\nWhat is your MOQ?\n\nThanks,\n[Your Name]", "")
    assert signed == "Hello,\n\nWhat is your MOQ?"


def test_sign_does_not_eat_a_bracketed_figure_mid_body() -> None:
    body = "We need 1,000 units [first batch] of the 50ml flacon.\n\nThanks,\n[Your Name]"
    assert "[first batch]" in sign(body, "Dana Reyes")
