"""
test_validation.py — чистые unit-тесты функций валидации.
Не требуют БД или HTTP-сервера.
"""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock

# Патчим зависимости ещё до импорта функций валидации
with patch("pg8000.connect", MagicMock()), \
     patch("bcrypt.checkpw", return_value=True):
    from app import validate_email, validate_phone, validate_text_field, validate_employee_data


# ═══════════════════════════════════════════════════════════
#  validate_email
# ═══════════════════════════════════════════════════════════

class TestValidateEmail:

    @pytest.mark.unit
    def test_valid_emails(self):
        """Корректные email-адреса проходят валидацию."""
        valid = [
            "user@example.com",
            "ivan.ivanov@company.ru",
            "test+tag@mail.org",
            "a@b.io",
        ]
        for email in valid:
            assert validate_email(email), f"Ожидался valid: {email}"

    @pytest.mark.unit
    def test_invalid_emails(self):
        """Некорректные email-адреса не проходят валидацию."""
        invalid = [
            "plaintext",
            "missing@",
            "@nodomain.com",
            "spaces in@email.com",
            "double@@domain.com",
        ]
        for email in invalid:
            assert not validate_email(email), f"Ожидался invalid: {email}"

    @pytest.mark.unit
    def test_empty_email_is_optional(self):
        """Пустой email считается допустимым (поле опциональное)."""
        assert validate_email("") is True
        assert validate_email(None) is True


# ═══════════════════════════════════════════════════════════
#  validate_phone
# ═══════════════════════════════════════════════════════════

class TestValidatePhone:

    @pytest.mark.unit
    def test_valid_phones(self):
        """Корректные телефонные номера проходят валидацию."""
        valid = [
            "+79991234567",
            "79991234567",
            "89991234567",
            "+7 (999) 123-45-67",
            "8(999)1234567",
        ]
        for phone in valid:
            assert validate_phone(phone), f"Ожидался valid: {phone}"

    @pytest.mark.unit
    def test_invalid_phones(self):
        """Некорректные телефоны не проходят валидацию."""
        invalid = [
            "123",               # слишком короткий
            "abcdefghijk",       # буквы
            "+1234567890123",    # слишком длинный
        ]
        for phone in invalid:
            assert not validate_phone(phone), f"Ожидался invalid: {phone}"

    @pytest.mark.unit
    def test_empty_phone_is_optional(self):
        """Пустой телефон считается допустимым (поле опциональное)."""
        assert validate_phone("") is True
        assert validate_phone(None) is True


# ═══════════════════════════════════════════════════════════
#  validate_text_field
# ═══════════════════════════════════════════════════════════

class TestValidateTextField:

    @pytest.mark.unit
    def test_required_field_empty_returns_error(self):
        """Обязательное пустое поле возвращает сообщение об ошибке."""
        result = validate_text_field("", "ФИО", required=True)
        assert result is not None
        assert "ФИО" in result

    @pytest.mark.unit
    def test_required_field_none_returns_error(self):
        result = validate_text_field(None, "Имя", required=True)
        assert result is not None

    @pytest.mark.unit
    def test_optional_field_empty_returns_none(self):
        """Необязательное пустое поле не возвращает ошибку."""
        assert validate_text_field("", "Описание", required=False) is None

    @pytest.mark.unit
    def test_min_length_violation(self):
        """Слишком короткое значение возвращает ошибку."""
        result = validate_text_field("А", "ФИО", min_length=2, required=True)
        assert result is not None
        assert "минимум" in result

    @pytest.mark.unit
    def test_max_length_violation(self):
        """Слишком длинное значение возвращает ошибку."""
        long_str = "А" * 201
        result = validate_text_field(long_str, "ФИО", max_length=200, required=True)
        assert result is not None
        assert "максимум" in result

    @pytest.mark.unit
    def test_valid_field_returns_none(self):
        """Корректное значение возвращает None (нет ошибок)."""
        assert validate_text_field("Иванов Иван Иванович", "ФИО", min_length=2, max_length=200) is None


# ═══════════════════════════════════════════════════════════
#  validate_employee_data
# ═══════════════════════════════════════════════════════════

class TestValidateEmployeeData:

    @pytest.mark.unit
    def test_valid_employee_no_errors(self):
        """Корректные данные сотрудника — пустой список ошибок."""
        data = {
            "full_name": "Иванов Иван Иванович",
            "position": "Менеджер",
            "department": "IT",
            "email": "ivanov@company.ru",
            "phone": "+79991234567",
        }
        errors = validate_employee_data(data)
        assert errors == []

    @pytest.mark.unit
    def test_missing_full_name(self):
        """Отсутствие ФИО — ошибка."""
        errors = validate_employee_data({"full_name": ""})
        assert len(errors) > 0

    @pytest.mark.unit
    def test_invalid_email_gives_error(self):
        """Невалидный email — ошибка."""
        data = {"full_name": "Тест Тест", "email": "not-an-email"}
        errors = validate_employee_data(data)
        assert any("email" in e.lower() for e in errors)

    @pytest.mark.unit
    def test_invalid_phone_gives_error(self):
        """Невалидный телефон — ошибка."""
        data = {"full_name": "Тест Тест", "phone": "abc"}
        errors = validate_employee_data(data)
        assert any("телефон" in e.lower() for e in errors)

    @pytest.mark.unit
    def test_multiple_errors_collected(self):
        """Все ошибки собираются в один список."""
        data = {"full_name": "", "email": "bad", "phone": "bad"}
        errors = validate_employee_data(data)
        assert len(errors) >= 2
