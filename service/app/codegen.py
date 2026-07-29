"""Short-code generation: random base62 codes with a collision check."""

import secrets
from typing import Callable

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


class CodeGenerationError(RuntimeError):
    pass


def generate_code(exists_fn: Callable[[str], bool], length: int, max_attempts: int) -> str:
    for _ in range(max_attempts):
        candidate = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if not exists_fn(candidate):
            return candidate
    raise CodeGenerationError(
        f"unable to generate a unique {length}-character code after {max_attempts} attempt(s)"
    )
