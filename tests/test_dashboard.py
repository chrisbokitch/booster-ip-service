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
