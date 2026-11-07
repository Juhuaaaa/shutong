"""Title and path-component rules shared by both libraries."""
import unicodedata


# Only the library's explicitly reviewed traditional-to-simplified mappings;
# a general converter would rewrite proper nouns.
TITLE_TRANSLATION = str.maketrans(
    {
        "與": "与",
        "後": "后",
        "門": "门",
        "菸": "烟",
    }
)


# Characters Windows and SMB shares refuse in file names, as their full-width look-alikes.
PATH_SAFE = str.maketrans({":": "：", "?": "？", "*": "＊", '"': "＂", "<": "＜", ">": "＞", "|": "｜"})


_DEVICE_NAMES = frozenset({"CON", "PRN", "AUX", "NUL"} | {"{0}{1}".format(name, number)
                                                         for name in ("COM", "LPT") for number in range(1, 10)})


def path_safe(name: str) -> str:
    """A name usable as a file or folder on every system: ``Re:ゼロ`` becomes ``Re：ゼロ``.

    Windows also drops trailing dots and spaces and refuses a few device names outright.
    """
    safe = name.translate(PATH_SAFE)
    safe = safe.rstrip(" .") or safe
    return safe + "_" if safe.split(".", 1)[0].upper() in _DEVICE_NAMES else safe


def normalize_title(title: str) -> str:
    """Apply only the library's explicit traditional-to-simplified mapping."""
    return title.translate(TITLE_TRANSLATION)


def is_safe_path_component(value: object) -> bool:
    """Return whether a value is one non-blank, non-special path component."""
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
        and not any(unicodedata.category(character) == "Cc" for character in value)
    )
