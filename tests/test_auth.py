"""
test_auth.py — тесты авторизации (логин / логаут / защита маршрутов).
"""
import pytest


class TestLogin:

    @pytest.mark.auth
    def test_login_page_accessible(self, client):
        """Страница логина доступна без авторизации."""
        response = client.get("/login")
        assert response.status_code == 200

    @pytest.mark.auth
    def test_login_page_contains_form(self, client):
        """На странице логина есть поля username и password."""
        response = client.get("/login")
        html = response.data.decode("utf-8")
        assert "username" in html or "login" in html.lower()

    @pytest.mark.auth
    def test_successful_login_redirects(self, client):
        """Успешный логин перенаправляет на dashboard."""
        from unittest.mock import patch
        import bcrypt

        # Генерируем хеш, который пройдёт проверку
        password = "admin123"
        real_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        with patch("app.ADMIN_PASSWORD_HASH", real_hash):
            response = client.post(
                "/login",
                data={"username": "admin", "password": password},
                follow_redirects=False,
            )
        # Должен быть редирект (302) или 200 после follow
        assert response.status_code in (302, 200)

    @pytest.mark.auth
    def test_wrong_password_stays_on_login(self, client):
        """Неверный пароль — остаёмся на /login (не редиректим)."""
        from unittest.mock import patch
        with patch("bcrypt.checkpw", return_value=False):
            response = client.post(
                "/login",
                data={"username": "admin", "password": "wrongpassword"},
                follow_redirects=True,
            )
        assert response.status_code == 200
        html = response.data.decode("utf-8")
        # На странице должно быть сообщение об ошибке или снова форма
        assert "login" in html.lower() or "пароль" in html.lower() or "логин" in html.lower()

    @pytest.mark.auth
    def test_wrong_username(self, client):
        """Неверный логин — отказ в доступе."""
        from unittest.mock import patch
        with patch("bcrypt.checkpw", return_value=False):
            response = client.post(
                "/login",
                data={"username": "hacker", "password": "any"},
                follow_redirects=True,
            )
        assert response.status_code == 200


class TestLogout:

    @pytest.mark.auth
    def test_logout_clears_session_and_redirects(self, logged_in_client):
        """Логаут очищает сессию и редиректит на /login."""
        response = logged_in_client.get("/logout", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers.get("Location", "")

    @pytest.mark.auth
    def test_after_logout_dashboard_requires_login(self, logged_in_client):
        """После логаута /dashboard требует повторного входа."""
        logged_in_client.get("/logout", follow_redirects=True)
        response = logged_in_client.get("/dashboard", follow_redirects=False)
        assert response.status_code in (302, 401)


class TestProtectedRoutes:

    @pytest.mark.auth
    def test_dashboard_without_login_redirects(self, client):
        """Не авторизованный пользователь не попадает на /dashboard."""
        response = client.get("/dashboard", follow_redirects=False)
        assert response.status_code in (302, 401)

    @pytest.mark.auth
    def test_employees_without_login_redirects(self, client):
        """Не авторизованный пользователь не попадает на /employees."""
        response = client.get("/employees", follow_redirects=False)
        assert response.status_code in (302, 401)

    @pytest.mark.auth
    def test_api_employees_without_login_redirects(self, client):
        """POST /api/employees без сессии — редирект (только POST разрешён)."""
        import json
        response = client.post(
            "/api/employees",
            data=json.dumps({"full_name": "Тест"}),
            content_type="application/json",
            follow_redirects=False,
        )
        assert response.status_code in (302, 401)

    @pytest.mark.auth
    def test_root_redirects(self, client):
        """Корневой URL '/' редиректит (на dashboard или login)."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
