"""
test_pages.py — smoke-тесты: проверка что страницы отдают 200 и рендерятся.
"""
import pytest
from unittest.mock import MagicMock


def _mock_stats_cursor(mock_cursor):
    """Настраивает курсор для dashboard (несколько fetchone)."""
    row = {"count": 0, "employees": 0, "keys": 0, "points": 0}
    mock_cursor.fetchone.return_value = row
    mock_cursor.fetchall.return_value = []


class TestPageSmoke:

    @pytest.mark.integration
    def test_login_page_loads(self, client):
        response = client.get("/login")
        assert response.status_code == 200
        assert b"<html" in response.data.lower() or b"login" in response.data.lower()

    @pytest.mark.integration
    def test_dashboard_loads_when_logged_in(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        _mock_stats_cursor(mock_cursor)

        response = logged_in_client.get("/dashboard")
        assert response.status_code == 200

    @pytest.mark.integration
    def test_employees_page_loads(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = {"count": 0}
        mock_cursor.fetchall.return_value = []

        response = logged_in_client.get("/employees")
        assert response.status_code == 200

    @pytest.mark.integration
    def test_keys_page_loads(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = {"count": 0}
        mock_cursor.fetchall.return_value = []

        response = logged_in_client.get("/keys")
        assert response.status_code == 200

    @pytest.mark.integration
    def test_groups_page_loads(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = {"count": 0}
        mock_cursor.fetchall.return_value = []

        response = logged_in_client.get("/groups")
        assert response.status_code == 200

    @pytest.mark.integration
    def test_logs_page_loads(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = {"count": 0}
        mock_cursor.fetchall.return_value = []

        response = logged_in_client.get("/logs")
        assert response.status_code == 200

    @pytest.mark.integration
    def test_nonexistent_page_returns_404(self, logged_in_client):
        response = logged_in_client.get("/this-page-does-not-exist-xyz")
        assert response.status_code == 404


class TestApiEndpointsStructure:
    """Проверка что API отвечает JSON-ом, а не HTML-ом."""

    @pytest.mark.integration
    def test_api_departments_content_type(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = {"exists": False}
        mock_cursor.fetchall.return_value = []

        response = logged_in_client.get("/api/departments")
        assert "application/json" in response.content_type

    @pytest.mark.integration
    def test_api_employees_post_returns_json(self, logged_in_client, mock_db):
        """POST /api/employees с невалидными данными → JSON (не HTML)."""
        import json as _json
        mock_conn, mock_cursor = mock_db

        # Пустое ФИО — ошибка валидации, но ответ всё равно JSON
        response = logged_in_client.post(
            "/api/employees",
            data=_json.dumps({"full_name": ""}),
            content_type="application/json",
        )
        assert "application/json" in response.content_type
        data = _json.loads(response.data)
        assert data.get("success") is False

    @pytest.mark.integration
    def test_metrics_endpoint_accessible(self, client):
        """Prometheus /metrics доступен без авторизации."""
        response = client.get("/metrics")
        assert response.status_code == 200
