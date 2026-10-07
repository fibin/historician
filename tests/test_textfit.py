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


def test_merge_to_glues_short_neighbours_until_limit():
    from historian.textfit import merge_to
    assert merge_to(["a", "bb", "c"], 2, 100, len) == ["a\n\nbb", "c"]
    assert merge_to(["a", "b", "c", "d"], 1, 100, len) == ["a\n\nb\n\nc\n\nd"]
    assert merge_to(["x" * 60, "y" * 60], 1, 100, len) == ["x" * 60, "y" * 60]  # не помещается — оставляем
    assert merge_to(["a", "b"], 5, 100, len) == ["a", "b"]
