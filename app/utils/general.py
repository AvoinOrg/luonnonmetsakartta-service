from ftfy import fix_text


def str_to_bool(value):
    return str(value).lower() in ("1", "true", "yes", "on")


def fix_encoding(text: str) -> str:
    """Fix encoding issues using ftfy library."""
    if not text:
        return text

    # ftfy automatically detects and fixes a wide range of encoding issues
    fixed_text = fix_text(text)

    return fixed_text
