from pathlib import Path


def test_health_check_answers_without_login(anon):
    response = anon.get("/healthz")
    assert (response.status_code, response.get_data(as_text=True)) == (200, "ok")


def test_every_template_compiles(app):
    """An invalid Jinja tag once reached production; catch it before deploy,
    including templates no other test renders."""
    root = Path(app.root_path) / "templates"
    names = [p.relative_to(root).as_posix() for p in root.rglob("*.html")]
    assert names
    for name in names:
        app.jinja_env.get_template(name)
