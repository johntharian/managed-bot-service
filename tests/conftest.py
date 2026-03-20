# tests/conftest.py
import pytest

# This sets asyncio_mode for all async tests in the project
# so you don't need to repeat @pytest.mark.asyncio on every test.
pytest_plugins = ["pytest_asyncio"]
