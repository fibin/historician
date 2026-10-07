"""Проверка длины постов и аккуратная нарезка, если модель промахнулась с лимитом."""
import re

URL_RE = re.compile(r"https?://\S+")
X_URL_WEIGHT = 23  # X считает любую ссылку как 23 символа


def _x_char_weight(ch: str) -> int:
    cp = ord(ch)
    # Латиница, кириллица и большая часть европейских алфавитов весят 1, CJK и эмодзи — 2.
    if cp <= 0x10FF or 0x2000 <= cp <= 0x200D or 0x2010 <= cp <= 0x201F or 0x2032 <= cp <= 0x2037:
        return 1
    return 2


def x_length(text: str) -> int:
    total, pos = 0, 0
    for m in URL_RE.finditer(text):
        total += sum(_x_char_weight(c) for c in text[pos:m.start()]) + X_URL_WEIGHT
        pos = m.end()
    return total + sum(_x_char_weight(c) for c in text[pos:])


def plain_length(text: str) -> int:
    return len(text)


def _split_one(text: str, limit: int, measure) -> list[str]:
    if measure(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    parts, current = [], ""
    for s in sentences:
        candidate = f"{current} {s}".strip()
        if measure(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        if measure(s) <= limit:
            current = s
        else:  # очень длинное предложение: режем по словам
            current = ""
            for word in s.split():
                candidate = f"{current} {word}".strip()
                if measure(candidate) <= limit:
                    current = candidate
                else:
                    parts.append(current)
                    current = word
    if current:
        parts.append(current)
    return parts


def fit(posts: list[str], limit: int, measure) -> list[str]:
    out = []
    for p in posts:
        p = p.strip()
        if p:
            out.extend(_split_one(p, limit, measure))
    return out
