from app.lens_service import PROPOSE_RULES, _tidy_proposal


def test_tidy_makes_tokens_canonical_and_drops_bad_parts() -> None:
    raw = {
        "label": "Coupe",
        "parts": [
            {"id": "Headlamp", "sam_prompt": "round headlamp"},
            {"id": "front", "sam_prompt": "front of the coupe showing bonnet and lamps"},
        ],
        "attributes": [
            {
                "key": "Bonnet Length",
                "label": "Bonnet",
                "category": "form",
                "kind": "ordinal",
                "scale": ["short bonnet", "very-long bonnet"],
            },
            {
                "key": "lamp_shape",
                "label": "Lamp",
                "category": "form",
                "kind": "enum",
                "vocabulary": ["Slim Oval", "round"],
                "part": "Headlamp",
            },
            {
                "key": "front_look",
                "label": "Front",
                "category": "form",
                "kind": "enum",
                "vocabulary": ["open"],
                "part": "front",
            },
        ],
    }
    out = _tidy_proposal(raw)
    assert [p["id"] for p in out["parts"]] == ["headlamp"]
    assert out["attributes"][0]["key"] == "bonnet_length"
    assert out["attributes"][0]["scale"] == ["short_bonnet", "very_long_bonnet"]
    assert out["attributes"][1]["vocabulary"] == ["slim_oval", "round"]
    assert out["attributes"][1]["part"] == "headlamp"
    assert out["attributes"][2]["part"] is None  # its part was dropped


def test_rules_name_the_constraints() -> None:
    assert "snake_case" in PROPOSE_RULES and "1-3 words" in PROPOSE_RULES
