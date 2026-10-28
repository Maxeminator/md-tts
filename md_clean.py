"""Превращает Obsidian-markdown в чистый текст, пригодный для озвучки."""
import re


def clean_markdown(md: str) -> str:
    text = md.replace("\r\n", "\n")

    # YAML frontmatter
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)

    # Блоки кода — в речи бесполезны
    text = re.sub(r"```.*?```", "\n", text, flags=re.S)
    text = re.sub(r"~~~.*?~~~", "\n", text, flags=re.S)
    # Inline code: оставляем содержимое
    text = re.sub(r"`([^`\n]+)`", r"\1", text)

    # Формулы
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.S)
    text = re.sub(r"\$[^$\n]+\$", " ", text)

    # HTML-комментарии и Obsidian-комментарии %% %%
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"%%.*?%%", "", text, flags=re.S)

    # Вложения ![[img.png]] и картинки ![alt](url)
    text = re.sub(r"!\[\[[^\]]*\]\]", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)

    # Wikilinks: [[note#heading|alias]] -> alias, иначе note
    def wikilink(m):
        inner = m.group(1)
        if "|" in inner:
            return inner.split("|", 1)[1]
        return inner.split("#", 1)[0].split("/")[-1]

    text = re.sub(r"\[\[([^\]]+)\]\]", wikilink, text)

    # Обычные ссылки [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # Голые URL
    text = re.sub(r"https?://\S+", "", text)

    # Callouts: > [!note] Title  -> Title
    text = re.sub(r"^>\s*\[![^\]]*\][+-]?\s*", "", text, flags=re.M)
    # Цитаты
    text = re.sub(r"^>\s?", "", text, flags=re.M)

    # Заголовки: убираем #, ставим точку для паузы
    def heading(m):
        t = m.group(1).strip().rstrip(".:")
        return f"\n{t}.\n"

    text = re.sub(r"^#{1,6}\s+(.+)$", heading, text, flags=re.M)

    # Горизонтальные линии
    text = re.sub(r"^\s*([-*_])(\s*\1){2,}\s*$", "\n", text, flags=re.M)

    # Таблицы: строка-разделитель убирается, ячейки через запятую
    text = re.sub(r"^[ 	]*\|?[ 	]*:?-{2,}:?[ 	]*(\|[ 	]*:?-{2,}:?[ 	]*)*\|?[ 	]*$", "", text, flags=re.M)

    def table_row(m):
        cells = [c.strip() for c in m.group(0).strip().strip("|").split("|")]
        return ", ".join(c for c in cells if c) + "."

    text = re.sub(r"^[ 	]*\|.*\|[ 	]*$", table_row, text, flags=re.M)

    # Чекбоксы и списки
    text = re.sub(r"^(\s*)[-*+]\s+\[[ xX]\]\s+", r"\1", text, flags=re.M)
    text = re.sub(r"^(\s*)[-*+]\s+", r"\1", text, flags=re.M)
    text = re.sub(r"^(\s*)\d+[.)]\s+", r"\1", text, flags=re.M)

    # Жирный/курсив/зачёркнутый/выделение
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text, flags=re.S)
    text = re.sub(r"(?<!\w)([*_])(?!\s)(.+?)(?<!\s)\1(?!\w)", r"\2", text, flags=re.S)
    text = re.sub(r"~~(.+?)~~", r"\1", text, flags=re.S)
    text = re.sub(r"==(.+?)==", r"\1", text, flags=re.S)

    # Block id ^abc123 в конце строки
    text = re.sub(r"[ 	]\^[\w-]+[ 	]*$", "", text, flags=re.M)
    # Теги #тег -> тег
    text = re.sub(r"(?<![\w&])#([\w/\-]+)", r"\1", text)
    # Сноски [^1]
    text = re.sub(r"\[\^[^\]]+\]:?", "", text)
    # HTML-теги
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>\n]+>", "", text)
    # Экранированные символы
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|>~])", r"\1", text)

    # Строки без финальной пунктуации -> точка, чтобы голос делал паузу
    lines = []
    for raw in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if not line:
            lines.append("")
            continue
        if line[-1] not in ".!?…:;,":
            line += "."
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


if __name__ == "__main__":
    import sys

    print(clean_markdown(open(sys.argv[1], encoding="utf-8").read()))
