"""Unit tests for the @txn decorator and registry (TEST_PLAN Layer 1)."""

from __future__ import annotations

import pytest

from safe_propose import txn
from safe_propose.registry import (
    DuplicateDefinitionError,
    UnknownDefinitionError,
    get_definition,
    registered_names,
)


def test_register_and_retrieve():
    @txn
    def first(batch, ctx):
        return "first"

    @txn
    def second(batch, ctx):
        return "second"

    assert registered_names() == ["first", "second"]
    assert get_definition("first") is first
    assert get_definition("second") is second


def test_decorator_returns_function_unchanged():
    @txn
    def callable_directly(batch, ctx):
        return 42

    assert callable_directly(None, None) == 42


def test_duplicate_name_raises():
    @txn
    def dup(batch, ctx):
        pass

    with pytest.raises(DuplicateDefinitionError):

        @txn
        def dup(batch, ctx):  # noqa: F811 - intentional duplicate
            pass


def test_unknown_name_lists_available():
    @txn
    def known(batch, ctx):
        pass

    with pytest.raises(UnknownDefinitionError) as exc:
        get_definition("missing")
    assert "known" in str(exc.value)
    assert "missing" in str(exc.value)
