"""ASGI entrypoint: ``uvicorn app.main.asgi:app``"""
from app.main.factory import create_app

app = create_app()
