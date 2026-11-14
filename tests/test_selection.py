import pytest

from pdf_touchup.model import Word
from pdf_touchup.selection import SelectionError, merge_selection

KWAME = Word("Kwame", (100, 90, 130, 101), (0, 0))
MENSAH = Word("Mensah", (133, 90, 170, 101), (0, 0))
MARCH = Word("March", (110, 110, 140, 121), (0, 1))


def test_merge_selection_joins_in_x_order():
    rect, text = merge_selection([MENSAH, KWAME])
    assert text == "Kwame Mensah"
    assert rect == (100, 90, 170, 101)


def test_merge_selection_rejects_two_lines():
    with pytest.raises(SelectionError):
        merge_selection([KWAME, MARCH])


def test_merge_selection_rejects_empty():
    with pytest.raises(SelectionError):
        merge_selection([])


def test_display_words_swaps_fixed_words():
    from pdf_touchup.model import Edit
    from pdf_touchup.selection import display_words

    edit = Edit(0, (100, 90, 170, 101), "Kwame Mensah", "Kwame Asante", None, "native")
    shown = display_words([KWAME, MENSAH, MARCH], [edit])
    texts = [w.text for w in shown]
    assert texts == ["March", "Kwame Asante"]
    fixed = shown[-1]
    assert fixed.rect == edit.rect and fixed.line_id == ("edit", 0)
