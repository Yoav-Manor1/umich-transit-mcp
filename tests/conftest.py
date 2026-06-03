"""Shared pytest fixtures."""
import os

# Ensure tests never accidentally read a developer's real .env
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("MBUS_BASE_URL", "https://mbus.example.test")
