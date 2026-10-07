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


def merge_to(posts: list[str], most: int, limit: int, measure) -> list[str]:
    """Если постов больше, чем most, склеивает соседние, пока склейка помещается в limit."""
    posts = list(posts)
    while len(posts) > most:
        sizes = [(measure(posts[i] + "\n\n" + posts[i + 1]), i) for i in range(len(posts) - 1)]
        size, i = min(sizes)
        if size > limit:
            break
        posts[i:i + 2] = [posts[i] + "\n\n" + posts[i + 1]]
    return posts
