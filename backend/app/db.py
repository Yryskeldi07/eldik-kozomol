from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


# Подключение к базе данных.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)

# Фабрика сессий SQLAlchemy.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """Базовый класс для моделей SQLAlchemy."""
    pass


def init_db() -> None:
    """Создаёт отсутствующие таблицы, описанные в models.py.

    Важно: create_all не удаляет существующие таблицы и записи
    и не изменяет структуру уже созданных таблиц.
    """
    # Импортируем модели, чтобы они зарегистрировались в Base.metadata.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db():
    """Выдаёт сессию БД и закрывает её после использования."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
