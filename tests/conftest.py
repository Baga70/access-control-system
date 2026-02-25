"""
conftest.py — общие фикстуры для всех тестов.

Использует unittest.mock для замены pg8000 и bcrypt,
чтобы тесты работали без реальной БД.
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Мок-объект для строки БД ────────────────────────────────────────────────

def make_row(**kwargs):
    """Создаёт dict-подобный объект — эмуляция строки из БД."""
    return dict(**kwargs)


# ─── Фикстура Flask-приложения ────────────────────────────────────────────────

@pytest.fixture(scope="session")
def app():
    """Возвращает тестовый экземпляр Flask-приложения."""
    # Патчим pg8000.connect ДО импорта app, чтобы не было реальных соединений
    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    # fetchone для различных вызовов вернёт минимальные данные
    mock_cursor.description = [("id",), ("name",)]
    mock_cursor.rowcount = 1
    mock_cursor.fetchone.return_value = {"count": 0, "exists": False}
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cursor

    with patch("pg8000.connect", return_value=mock_conn), \
         patch("bcrypt.checkpw", return_value=True):

        import app as flask_app_module
        flask_app = flask_app_module.app
        flask_app.config.update({
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "WTF_CSRF_ENABLED": False,
        })
        yield flask_app


@pytest.fixture
def client(app):
    """HTTP-клиент Flask для тестовых запросов."""
    return app.test_client()


@pytest.fixture
def logged_in_client(client):
    """HTTP-клиент с уже выполненным логином (сессия active)."""
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "admin"
    return client


@pytest.fixture
def mock_db():
    """
    Патч get_db_connection и close_db_connection для теста.
    Возвращает (mock_conn, mock_cursor) для настройки ответов.
    """
    mock_conn   = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = []
    mock_cursor.rowcount = 1
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.get_db_connection", return_value=mock_conn), \
         patch("app.close_db_connection"):
        yield mock_conn, mock_cursor
