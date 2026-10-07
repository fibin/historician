"""Тонкая обёртка над Claude API: стриминг, pause_turn, отказ модели."""
import anthropic

from .config import MODEL

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ModelRefused(RuntimeError):
    pass


def run(client: anthropic.Anthropic, *, system: str, user: str, tools=None,
        output_config=None, effort: str = "high", max_tokens: int = 32000, max_continuations: int = 6):
    """Один запрос с продолжением после pause_turn (долгий веб-поиск)."""
    messages = [{"role": "user", "content": user}]
    kwargs = dict(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        thinking={"type": "adaptive"},
    )
    if tools:
        kwargs["tools"] = tools
    kwargs["output_config"] = {"effort": effort, **(output_config or {})}

    for _ in range(max_continuations + 1):
        with client.beta.messages.stream(messages=messages, **kwargs) as stream:
            response = stream.get_final_message()
        if response.stop_reason == "refusal":
            raise ModelRefused(str(response.stop_details))
        if response.stop_reason != "pause_turn":
            return response
        messages = messages[:1] + [{"role": "assistant", "content": response.content}]
    raise RuntimeError("Поиск не завершился за отведённое число продолжений")


def text_of(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text").strip()


def sources_of(response) -> list[dict]:
    """Все URL, которые реально вернул веб-поиск, без дублей."""
    seen, out = set(), []
    for block in response.content:
        if block.type != "web_search_tool_result" or not isinstance(block.content, list):
            continue
        for r in block.content:
            url = getattr(r, "url", None)
            if url and url not in seen:
                seen.add(url)
                out.append({"url": url, "title": getattr(r, "title", "")})
    return out
