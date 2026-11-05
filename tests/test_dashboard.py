from fastapi.testclient import TestClient
from app import main


def test_dashboard_is_served():
    client = TestClient(main.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Booster IP Service" in response.text
    assert 'src="/static/app.js"' in response.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_existing_api_routes_still_exist():
    paths = {route.path for route in main.app.routes}
    assert "/api/v1/data" in paths
    assert "/api/v1/data.txt" in paths
    assert "/api/v1/sources/{source_id}/refresh" in paths


def test_dashboard_and_editor_are_separate():
    client = TestClient(main.app)
    home = client.get("/")
    editor = client.get("/edit")
    assert home.status_code == 200
    assert editor.status_code == 200
    assert 'id="add-source"' not in home.text
    assert 'id="source-form"' not in home.text
    assert 'id="add-source"' in editor.text
    assert 'id="source-form"' in editor.text
    assert 'href="/edit"' in home.text
    assert 'href="/"' in editor.text
    assert 'id="refresh-all"' in home.text
    assert 'id="history-dialog"' in home.text
