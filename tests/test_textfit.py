from historian.textfit import fit, plain_length


def test_fit_keeps_short_posts():
    assert fit(["a", " ", "b"], 500, plain_length) == ["a", "b"]


def test_fit_splits_on_sentences():
    text = ". ".join(["Речення номер " + str(i) for i in range(40)]) + "."
    parts = fit([text], 100, plain_length)
    assert len(parts) > 1
    assert all(len(p) <= 100 for p in parts)
    assert " ".join(parts).replace("  ", " ") == text


def test_fit_splits_giant_sentence_by_words():
    text = " ".join(["слово"] * 200)
    parts = fit([text], 50, plain_length)
    assert all(len(p) <= 50 for p in parts)
    assert " ".join(parts) == text
