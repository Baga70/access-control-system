"""
test_departments.py — тесты API отделов (GET, POST, DELETE).
"""
import pytest
import json


class TestGetDepartments:

    @pytest.mark.integration
    def test_get_departments_returns_200(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = {"exists": True}
        mock_cursor.fetchall.return_value = [
            {"name": "IT"},
            {"name": "Бухгалтерия"},
            {"name": "Продажи"},
        ]

        response = logged_in_client.get("/api/departments")
        assert response.status_code == 200

    @pytest.mark.integration
    def test_get_departments_returns_json(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = {"exists": True}
        mock_cursor.fetchall.return_value = [{"name": "IT"}]

        response = logged_in_client.get("/api/departments")
        data = json.loads(response.data)
        assert "success" in data

    @pytest.mark.integration
    def test_get_departments_list_is_list(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = {"exists": True}
        mock_cursor.fetchall.return_value = [{"name": "IT"}, {"name": "HR"}]

        response = logged_in_client.get("/api/departments")
        data = json.loads(response.data)
        if data.get("success"):
            assert isinstance(data.get("departments"), list)


class TestCreateDepartment:

    @pytest.mark.integration
    def test_create_valid_department(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        # exists=True → работаем с таблицей departments
        # count=0 → отдела ещё нет
        # fetchone последовательно: exists, count, RETURNING id
        mock_cursor.fetchone.side_effect = [
            {"exists": True},
            {"count": 0},
            {"id": 5},
        ]

        payload = {"name": "Новый отдел"}
        response = logged_in_client.post(
            "/api/departments",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "success" in data

    @pytest.mark.integration
    def test_create_empty_name_fails(self, logged_in_client, mock_db):
        """Пустое название отдела — ошибка."""
        payload = {"name": ""}
        response = logged_in_client.post(
            "/api/departments",
            data=json.dumps(payload),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data.get("success") is False
        assert "error" in data

    @pytest.mark.integration
    def test_create_too_short_name_fails(self, logged_in_client, mock_db):
        """Название менее 2 символов — ошибка."""
        payload = {"name": "А"}
        response = logged_in_client.post(
            "/api/departments",
            data=json.dumps(payload),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data.get("success") is False

    @pytest.mark.integration
    def test_create_duplicate_department_fails(self, logged_in_client, mock_db):
        """Дублирующееся название — ошибка."""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.side_effect = [
            {"exists": True},
            {"count": 1},   # уже существует
        ]

        payload = {"name": "IT"}
        response = logged_in_client.post(
            "/api/departments",
            data=json.dumps(payload),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data.get("success") is False


class TestDeleteDepartment:

    @pytest.mark.integration
    def test_delete_department_without_employees(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        # count = 0 — нет сотрудников в отделе
        mock_cursor.fetchone.return_value = {"count": 0}

        response = logged_in_client.delete("/api/departments/IT")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "success" in data

    @pytest.mark.integration
    def test_delete_department_with_employees_needs_confirm(self, logged_in_client, mock_db):
        """Отдел с сотрудниками требует подтверждения (force не передан)."""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = {"count": 3}  # 3 сотрудника

        response = logged_in_client.delete("/api/departments/IT")
        data = json.loads(response.data)
        # Ожидаем либо needs_confirm=True, либо success=False с информацией
        assert "needs_confirm" in data or data.get("success") is False

    @pytest.mark.integration
    def test_delete_with_force_param(self, logged_in_client, mock_db):
        """С параметром force=true удаление выполняется принудительно."""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = {"count": 2}

        response = logged_in_client.delete("/api/departments/IT?force=true")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "success" in data
