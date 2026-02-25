"""
test_employees.py — интеграционные тесты API сотрудников.
Все запросы к БД замокированы через фикстуру mock_db.

Реальная структура маршрутов:
  POST   /api/employees           — создание сотрудника
  PUT    /api/employees/<id>      — обновление
  DELETE /api/employees/<id>      — удаление (всегда success=True, если нет исключения)
  GET    /employees               — HTML-страница со списком сотрудников
"""
import pytest
import json


# ─── Вспомогательная функция ──────────────────────────────

def _emp_row(**kwargs):
    """Минимальная строка сотрудника из БД."""
    defaults = {
        "id": 1,
        "full_name": "Иванов Иван Иванович",
        "position": "Инженер",
        "department": "IT",
        "email": "ivanov@test.ru",
        "phone": "+79991234567",
        "is_active": True,
        "created_at": "2024-01-01 00:00:00",
        "card_number": "CARD-001",
        "access_level_id": None,
    }
    defaults.update(kwargs)
    return defaults


# ═══════════════════════════════════════════════════════════
#  GET /employees  (HTML-страница, не API)
# ═══════════════════════════════════════════════════════════

class TestEmployeesPage:

    @pytest.mark.integration
    def test_employees_page_returns_200(self, logged_in_client, mock_db):
        """GET /employees возвращает HTML-страницу."""
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchall.return_value = [_emp_row()]

        response = logged_in_client.get("/employees")
        assert response.status_code == 200

    @pytest.mark.integration
    def test_employees_page_contains_html(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchall.return_value = []

        response = logged_in_client.get("/employees")
        assert b"<html" in response.data.lower() or b"<!doctype" in response.data.lower()

    @pytest.mark.integration
    def test_employees_page_requires_login(self, client):
        """Без авторизации — редирект на /login."""
        response = client.get("/employees", follow_redirects=False)
        assert response.status_code == 302
        assert "login" in response.headers.get("Location", "").lower()


# ═══════════════════════════════════════════════════════════
#  POST /api/employees  (создание)
# ═══════════════════════════════════════════════════════════

class TestCreateEmployee:

    @pytest.mark.integration
    def test_create_requires_login(self, client):
        """Без авторизации POST /api/employees — редирект."""
        response = client.post(
            "/api/employees",
            data=json.dumps({"full_name": "Тест"}),
            content_type="application/json",
            follow_redirects=False,
        )
        assert response.status_code == 302

    @pytest.mark.integration
    def test_create_with_valid_data_returns_200(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = {"id": 99}

        payload = {
            "full_name": "Сидоров Сидор Сидорович",
            "position": "Менеджер",
            "department": "Продажи",
            "email": "sidorov@test.ru",
            "phone": "+79001234567",
        }
        response = logged_in_client.post(
            "/api/employees",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert response.status_code == 200

    @pytest.mark.integration
    def test_create_response_is_json(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = {"id": 1}

        payload = {"full_name": "Тест Тестович", "position": "Тестер"}
        response = logged_in_client.post(
            "/api/employees",
            data=json.dumps(payload),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert "success" in data

    @pytest.mark.integration
    def test_create_without_full_name_fails(self, logged_in_client, mock_db):
        """Создание без ФИО → success=False (ошибка валидации, до обращения к БД)."""
        payload = {"position": "Менеджер"}
        response = logged_in_client.post(
            "/api/employees",
            data=json.dumps(payload),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data.get("success") is False
        assert "error" in data

    @pytest.mark.integration
    def test_create_with_empty_full_name_fails(self, logged_in_client, mock_db):
        payload = {"full_name": ""}
        response = logged_in_client.post(
            "/api/employees",
            data=json.dumps(payload),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data.get("success") is False

    @pytest.mark.integration
    def test_create_with_invalid_email_fails(self, logged_in_client, mock_db):
        """Невалидный email — ошибка валидации."""
        payload = {"full_name": "Тест Тест", "email": "not-an-email"}
        response = logged_in_client.post(
            "/api/employees",
            data=json.dumps(payload),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data.get("success") is False

    @pytest.mark.integration
    def test_create_with_invalid_phone_fails(self, logged_in_client, mock_db):
        """Невалидный телефон — ошибка валидации."""
        payload = {"full_name": "Тест Тест", "phone": "abcdef"}
        response = logged_in_client.post(
            "/api/employees",
            data=json.dumps(payload),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data.get("success") is False

    @pytest.mark.integration
    def test_create_with_short_name_fails(self, logged_in_client, mock_db):
        """ФИО менее 2 символов — ошибка валидации."""
        payload = {"full_name": "А"}
        response = logged_in_client.post(
            "/api/employees",
            data=json.dumps(payload),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data.get("success") is False


# ═══════════════════════════════════════════════════════════
#  PUT /api/employees/<id>  (обновление)
# ═══════════════════════════════════════════════════════════

class TestUpdateEmployee:

    @pytest.mark.integration
    def test_update_existing_employee_returns_200(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db
        mock_cursor.fetchone.return_value = _emp_row()

        payload = {"full_name": "Новое Имя Фамилия", "position": "Директор"}
        response = logged_in_client.put(
            "/api/employees/1",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert response.status_code == 200

    @pytest.mark.integration
    def test_update_returns_json_with_success(self, logged_in_client, mock_db):
        mock_conn, mock_cursor = mock_db

        payload = {"full_name": "Обновлённое Имя"}
        response = logged_in_client.put(
            "/api/employees/1",
            data=json.dumps(payload),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert "success" in data

    @pytest.mark.integration
    def test_update_with_empty_full_name_fails(self, logged_in_client, mock_db):
        """Обновление с пустым ФИО — ошибка валидации."""
        payload = {"full_name": ""}
        response = logged_in_client.put(
            "/api/employees/1",
            data=json.dumps(payload),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data.get("success") is False

    @pytest.mark.integration
    def test_update_requires_login(self, client):
        response = client.put(
            "/api/employees/1",
            data=json.dumps({"full_name": "Тест"}),
            content_type="application/json",
            follow_redirects=False,
        )
        assert response.status_code == 302


# ═══════════════════════════════════════════════════════════
#  DELETE /api/employees/<id>
# ═══════════════════════════════════════════════════════════

class TestDeleteEmployee:

    @pytest.mark.integration
    def test_delete_returns_200(self, logged_in_client, mock_db):
        """DELETE всегда возвращает 200 (API не проверяет существование)."""
        response = logged_in_client.delete("/api/employees/1")
        assert response.status_code == 200

    @pytest.mark.integration
    def test_delete_returns_json(self, logged_in_client, mock_db):
        response = logged_in_client.delete("/api/employees/1")
        data = json.loads(response.data)
        assert "success" in data

    @pytest.mark.integration
    def test_delete_returns_success_true(self, logged_in_client, mock_db):
        """Мок-курсор не бросает исключение → success=True."""
        response = logged_in_client.delete("/api/employees/42")
        data = json.loads(response.data)
        assert data.get("success") is True

    @pytest.mark.integration
    def test_delete_requires_login(self, client):
        response = client.delete("/api/employees/1", follow_redirects=False)
        assert response.status_code == 302
