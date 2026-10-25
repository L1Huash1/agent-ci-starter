"""Synthetic reference code; the lab packs this file but does not execute it."""


NOTES = {"release": "Review interface changes before releasing."}


def lookup_note(note_id):
    """Return a note from an in-memory dictionary."""
    return {"note_id": note_id, "text": NOTES[note_id]}


def unrelated_example():
    return "Outside the selected line range."
