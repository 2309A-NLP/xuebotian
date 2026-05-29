SUPPORTED_UPLOAD_SUFFIXES = {".json", ".txt", ".pdf", ".docx"}
TEXT_FIELD_CANDIDATES = ("message", "content", "text", "description", "intro")
NAME_FIELD_CANDIDATES = ("name", "character_name", "title")
SOURCE_FIELD_CANDIDATES = ("source_file", "source", "saved_name", "original_name")
SUMMARY_FIELD_CANDIDATES = ("summary", "profile_summary", "bio", "brief")
ALIAS_FIELD_CANDIDATES = ("alias", "aliases", "nickname", "nicknames")
ZERO_WIDTH_TRANSLATION = dict.fromkeys(map(ord, "\ufeff\u200b\u200c\u200d\u2060"), None)
WHITESPACE_TRANSLATION = str.maketrans(
    {"\u00a0": " ", "\u3000": " ", "\t": " ", "\r": "\n"}
)
