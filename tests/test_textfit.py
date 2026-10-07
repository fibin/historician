from historian.textfit import fit, plain_length, x_length


def test_cyrillic_counts_as_one():
    assert x_length("привет") == 6


def test_url_counts_as_23():
    assert x_length("см. https://example.com/very/long/path/that/is/long") == 4 + 23


def test_emoji_and_cjk_count_double():
    assert x_length("漢") == 2
    assert x_length("📜") == 2


def test_fit_keeps_short_posts():
    assert fit(["a", " ", "b"], 280, x_length) == ["a", "b"]


def test_fit_splits_on_sentences():
    text = ". ".join(["Предложение номер " + str(i) for i in range(40)]) + "."
    parts = fit([text], 100, x_length)
    assert len(parts) > 1
    assert all(x_length(p) <= 100 for p in parts)
    assert " ".join(parts).replace("  ", " ") == text


def test_fit_splits_giant_sentence_by_words():
    text = " ".join(["слово"] * 200)
    parts = fit([text], 50, plain_length)
    assert all(len(p) <= 50 for p in parts)
    assert " ".join(parts) == text
