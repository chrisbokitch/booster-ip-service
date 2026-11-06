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
    assert "/api/v1/data.txt" not in paths
    assert "/api/v1/sources/{source_id}/records" not in paths
    assert "/api/v1/sources/{source_id}/refresh" in paths



def test_inline_edit_mode_markup():
    client = TestClient(main.app)
    home = client.get("/")
    assert home.status_code == 200
    assert 'id="toggle-edit"' in home.text
    assert 'id="add-source" type="button" hidden' in home.text
    assert 'id="edit-warning-dialog"' in home.text
    assert 'id="confirm-edit-warning"' in home.text
    assert 'id="cancel-edit-warning"' in home.text
    assert 'id="source-form"' in home.text
    assert 'id="refresh-all"' in home.text
    assert 'id="output-list"' in home.text
    assert 'id="output-custom"' in home.text
    for field in ("header", "entry", "separator", "footer"):
        assert f'id="output-{field}"' in home.text
    assert 'id="output-template-wrap" class="output-template-fields" hidden' in home.text
    assert 'id="history-dialog"' in home.text
    assert client.get("/edit").status_code == 404
    js = client.get("/static/app.js").text
    assert 'el("edit-warning-dialog").showModal()' in js
    assert 'setEditMode(true)' in js
    assert 'setEditMode(false)' in js
    assert 'entry.replaceAll("{value}", value)' in js
    assert 'localStorage.setItem(formatterKey' in js
    assert 'restoreFormatter();' in js
    assert 'if (editMode) actions.append(remove)' in js


def test_page_size_handlers_do_not_include_output_mode_buttons():
    from pathlib import Path
    script = Path(main.__file__).parent / 'static' / 'app.js'
    js = script.read_text(encoding='utf-8')
    assert 'document.querySelectorAll(".page-size-control .page-preset")' in js
    assert 'document.querySelectorAll(".page-preset")' not in js


def test_output_sidebar_settings_are_persisted():
    from pathlib import Path
    js = (Path(main.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    assert 'const settingsKey = "booster-ip-service.output-settings.v1"' in js
    assert "localStorage.setItem(settingsKey" in js
    assert "restoreOutputSettings();" in js
    assert "savedSourceIds.filter(id => enabledIds.includes(id))" in js
    assert "saveOutputSettings();" in js


def test_source_refresh_feedback_uses_card_footer():
    client = TestClient(main.app)
    js = client.get("/static/app.js").text
    css = client.get("/static/style.css").text
    assert 'setSourceNotice(row.id, "Refreshing…")' in js
    assert 'setSourceNotice(row.id, "Refresh complete.")' in js
    assert 'sourceNotices.get(row.id)' in js
    assert '"source-footer"' in js
    assert '.source-footer{' in css
    assert 'height:30px' in css


def test_source_save_and_remove_use_card_footers():
    client = TestClient(main.app)
    js = client.get("/static/app.js").text
    assert 'setSourceNotice(editingSource || payload.id' in js
    assert 'setSourceNotice(row.id, "Remove failed: "' in js
    assert '"Source removed.", "source-footer"' in js
    assert 'sourceMessage(' not in js
