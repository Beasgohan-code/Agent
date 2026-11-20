"""Bounded literal media-name rules; no regex evaluation or upstream imports."""
DELETE_KEY = 'media_delete_words'
REPLACE_KEY = 'media_replace_words'
MAX_RULES = 20
MAX_WORD = 64


def transform(chats, chat_id, text):
    """Apply replacements once, then deletions; never cascade replacements."""
    if chats is None:
        return text
    replacements = chats.get(chat_id, REPLACE_KEY, {})
    deletions = chats.get(chat_id, DELETE_KEY, [])
    pairs = {k: v for k, v in replacements.items()
             if isinstance(k, str) and k and len(k) <= MAX_WORD
             and isinstance(v, str) and len(v) <= MAX_WORD} if isinstance(replacements, dict) else {}
    words = [word for word in deletions if isinstance(word, str) and word and len(word) <= MAX_WORD] if isinstance(deletions, list) else []
    # Longest-match-first, literal and case-sensitive; substitutions are not
    # reprocessed, so a->b and b->a cannot loop or balloon the output.
    rules = {key: value for key, value in list(pairs.items())[:MAX_RULES]}
    for word in words[:MAX_RULES]:
        rules[word] = ''
    if not rules:
        return text
    import re
    pattern = re.compile('|'.join(re.escape(key) for key in sorted(rules, key=len, reverse=True)))
    return pattern.sub(lambda match: rules[match.group(0)], text)
