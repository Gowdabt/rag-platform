from app.core.untrusted import untrusted_text


def test_untrusted_text_strips_html_and_control_chars():
    raw = "<img src=x onerror=alert(1)>hello\x00<script>alert(1)</script>"
    assert untrusted_text(raw) == "helloalert(1)"
    assert "<" not in untrusted_text("<b>title</b>")
    assert untrusted_text(None) == ""
    assert len(untrusted_text("a" * 5000)) == 2048
