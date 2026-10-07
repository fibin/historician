"""Проверка длины постов и аккуратная нарезка, если модель промахнулась с лимитом."""
import re

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
