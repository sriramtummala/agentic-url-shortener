import pytest

from service.app.codegen import CodeGenerationError, generate_code


def test_generate_code_returns_requested_length():
    code = generate_code(lambda c: False, length=7, max_attempts=5)
    assert len(code) == 7


def test_generate_code_retries_on_collision():
    seen = []

    def exists_fn(code):
        seen.append(code)
        return len(seen) < 3  # first two "collide", third attempt is free

    code = generate_code(exists_fn, length=7, max_attempts=5)
    assert len(seen) == 3
    assert len(code) == 7


def test_generate_code_raises_after_max_attempts():
    with pytest.raises(CodeGenerationError):
        generate_code(lambda c: True, length=7, max_attempts=3)
