from app.notes.visualize import note_prompt


def test_note_prompt_with_and_without_context() -> None:
    assert note_prompt("a honey jar", "Kitchen", "warm, quiet") == (
        "a honey jar. Board: Kitchen — warm, quiet. Product photo, plain background."
    )
    assert note_prompt("a honey jar.", "Kitchen", None) == (
        "a honey jar. Board: Kitchen. Product photo, plain background."
    )
    assert note_prompt("a honey jar", "", "") == "a honey jar. Product photo, plain background."
