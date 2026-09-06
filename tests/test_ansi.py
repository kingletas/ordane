from ordane.presentation.ansi import to_html


def test_a_coloured_run_becomes_a_span():
    assert to_html("\x1b[0;32mok\x1b[0m") == '<span class="a-green">ok</span>'


def test_plain_text_is_returned_unchanged():
    assert to_html("TASK [Gathering Facts]") == "TASK [Gathering Facts]"


def test_markup_in_the_output_is_escaped_not_rendered():
    assert to_html("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_markup_inside_a_coloured_run_is_still_escaped():
    assert "&lt;img" in to_html("\x1b[31m<img onerror=x>\x1b[0m")
    assert "<img" not in to_html("\x1b[31m<img onerror=x>\x1b[0m")


def test_an_unterminated_colour_is_closed_at_the_end():
    result = to_html("\x1b[33mchanged")
    assert result.startswith('<span class="a-yellow">')
    assert result.endswith("</span>")


def test_bold_and_colour_combine():
    assert to_html("\x1b[1;31mfatal\x1b[0m") == '<span class="a-red a-bold">fatal</span>'


def test_a_cursor_escape_is_removed_rather_than_printed():
    assert to_html("clean\x1b[2Ktext") == "cleantext"


def test_a_reset_closes_every_open_span():
    result = to_html("\x1b[31ma\x1b[33mb\x1b[0mc")
    assert result.count("<span") == result.count("</span>")
    assert result.endswith("c")
