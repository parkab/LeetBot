import re
from typing import TYPE_CHECKING

import discord
from bs4 import BeautifulSoup, NavigableString, Tag

if TYPE_CHECKING:
    from leetbot.leetcode import DailyProblem

DIFFICULTY_COLORS = {
    "Easy": 0x00B8A9,
    "Medium": 0xFFA116,
    "Hard": 0xFF375F,
}


def _node_to_md(node: object) -> str:
    """Recursively convert a BeautifulSoup node to Discord markdown."""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""

    tag = node.name
    inner = "".join(_node_to_md(c) for c in node.children)

    # Inline formatting → Discord markdown (no newlines added)
    if tag in ("strong", "b"):
        s = inner.strip()
        return f"**{s}**" if s else ""
    if tag in ("em", "i"):
        s = inner.strip()
        return f"*{s}*" if s else ""
    if tag == "code":
        s = inner.strip()
        return f"`{s}`" if s else ""
    if tag == "sup":
        return f"^{inner}"
    if tag == "a":
        href = node.get("href", "")
        s = inner.strip()
        return f"[{s}]({href})" if href and s else inner

    # Block elements → add surrounding newlines
    if tag == "br":
        return "\n"
    if tag == "p":
        return inner.strip() + "\n\n"
    if tag in ("h1", "h2", "h3", "h4"):
        return "**" + inner.strip() + "**\n\n"
    if tag == "li":
        return "• " + inner.strip() + "\n"
    if tag in ("ul", "ol"):
        return inner.strip() + "\n\n"
    if tag == "pre":
        return inner.strip() + "\n\n"

    # Skip non-content tags entirely
    if tag in ("script", "style", "img"):
        return ""

    return inner


def html_to_text(html: str, max_chars: int = 900) -> str:
    soup = BeautifulSoup(html, "html.parser")
    text = _node_to_md(soup)
    # Collapse 3+ newlines to 2, clean up spaces around newlines
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0] + "\n…"
    return text


def build_daily_embed(problem: "DailyProblem", day_key: str) -> discord.Embed:
    color = DIFFICULTY_COLORS.get(problem.difficulty, 0x7289DA)
    description = html_to_text(problem.content_html)
    embed = discord.Embed(
        title=f"📅 Daily Challenge — {day_key}",
        description=f"**[{problem.title}]({problem.url})**\n\n{description}",
        color=color,
    )
    embed.add_field(name="Difficulty", value=problem.difficulty, inline=True)
    embed.set_footer(text="Use /solve to start your interview • /leaderboard daily for scores")
    return embed


def extract_code_block(text: str) -> str:
    """Return contents of a ```...``` fence, or the raw text if none found."""
    match = re.search(r"```(?:python|py)?\n?(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()
