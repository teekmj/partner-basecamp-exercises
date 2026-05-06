"""Tests for the Presentation mode (slide deck)."""

import pytest

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_presentation_mode_in_html(client):
    """The 'present' mode is wired into the top-nav and has a slide stage."""
    body = client.get("/").data.decode("utf-8")
    assert 'data-mode="present"' in body
    assert "Solution Presentation" in body
    assert 'id="slide-stage"' in body
    assert 'id="btn-slide-next"' in body


def test_app_js_has_slide_machinery(client):
    body = client.get("/static/app.js").data.decode("utf-8")
    assert "loadPresentation" in body
    assert "showSlide" in body
    assert "SLIDES" in body


def test_run_panel_has_qa_and_demo_tabs(client):
    body = client.get("/").data.decode("utf-8")
    assert 'data-tab="qa"' in body
    assert 'data-tab="demo"' in body
    assert "QA Scorecard" in body
    assert "Demo Notes" in body


def test_pipeline_visualizer_shows_six_stages(client):
    body = client.get("/").data.decode("utf-8")
    for stage in ["parse", "retrieve_draft", "review", "qa_review", "demo", "export"]:
        assert f'data-stage="{stage}"' in body, f"Missing stage card: {stage}"


def test_parallel_toggle_present(client):
    body = client.get("/").data.decode("utf-8")
    assert 'id="opt-parallel"' in body
    assert "parallel" in body.lower()
