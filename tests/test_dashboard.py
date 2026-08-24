from pathlib import Path


def test_repeated_login_prompt_does_not_steal_password_focus():
    dashboard = (
        Path(__file__).parents[1]
        / "src"
        / "jarvis_home"
        / "static"
        / "index.html"
    ).read_text()
    assert "opening=!loginOverlay.classList.contains('show')" in dashboard
    assert "if(opening)loginUsername.focus()" in dashboard
