"""Shared pytest fixtures."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make ui/ importable
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def mock_anthropic_client():
    """A mock anthropic.Anthropic client whose .messages.create returns
    a configurable response. Tests override .response per-test."""
    client = MagicMock()
    client.messages.create = MagicMock()
    return client


@pytest.fixture
def make_text_response():
    """Factory: build a response object that mimics Anthropic's API shape."""
    def _make(text, stop_reason="end_turn"):
        resp = MagicMock()
        resp.stop_reason = stop_reason
        block = MagicMock()
        block.type = "text"
        block.text = text
        resp.content = [block]
        return resp
    return _make


@pytest.fixture
def make_tool_use_response():
    """Factory: build a response object with tool_use stop_reason."""
    def _make(tool_name, tool_input, tool_use_id="tool_001"):
        resp = MagicMock()
        resp.stop_reason = "tool_use"
        block = MagicMock()
        block.type = "tool_use"
        block.name = tool_name
        block.input = tool_input
        block.id = tool_use_id
        resp.content = [block]
        return resp
    return _make
