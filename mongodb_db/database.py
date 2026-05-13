from __future__ import annotations

import threading
from typing import Optional

from mongoengine import connect, disconnect
from pymongo import MongoClient

from .settings import settings


class DatabaseConfig:
    """MongoDB connection manager and database name registry."""

    MONGODB_HOST: str = settings.MONGODB_HOST
    MONGODB_PORT: int = settings.MONGODB_PORT

    # Database name constants
    DB_DEVELOPMENT = "Development"
    DB_TEST = "Test"
    DB_UAT = "UAT"
    DB_PRODUCTION = "Production"
    DB_USER_TEMP = "User_Temp"
    DB_DEVELOPMENT_LOGS = "DevelopmentLogs"
    DB_TEST_LOGS = "TestLogs"
    DB_UAT_LOGS = "UATLogs"
    DB_PRODUCTION_LOGS = "ProductionLogs"

    _connections: dict = {}

    @classmethod
    def get_db_name(cls, environment: str) -> str:
        return {
            "development": cls.DB_DEVELOPMENT,
            "test": cls.DB_TEST,
            "uat": cls.DB_UAT,
            "production": cls.DB_PRODUCTION,
            "user_temp": cls.DB_USER_TEMP,
        }.get(environment.lower(), cls.DB_DEVELOPMENT)

    @classmethod
    def get_logs_db_name(cls, environment: str) -> str:
        return {
            "development": cls.DB_DEVELOPMENT_LOGS,
            "test": cls.DB_TEST_LOGS,
            "uat": cls.DB_UAT_LOGS,
            "production": cls.DB_PRODUCTION_LOGS,
        }.get(environment.lower(), cls.DB_DEVELOPMENT_LOGS)

    @classmethod
    def connect_to_db(cls, environment: str = "development", alias: Optional[str] = None) -> None:
        alias = alias or environment
        connection = connect(
            db=cls.get_db_name(environment),
            host=cls.MONGODB_HOST,
            port=cls.MONGODB_PORT,
            alias=alias,
            uuidRepresentation="standard",
        )
        cls._connections[alias] = connection

    @classmethod
    def disconnect_from_db(cls, alias: Optional[str] = None) -> None:
        disconnect(alias=alias)
        if alias and alias in cls._connections:
            del cls._connections[alias]

    @classmethod
    def disconnect_all(cls) -> None:
        for alias in list(cls._connections.keys()):
            cls.disconnect_from_db(alias)

    @classmethod
    def ensure_ttl_indexes(cls) -> None:
        """Ensure expires_at TTL index exists on every User_Temp collection."""
        try:
            client = MongoClient(host=cls.MONGODB_HOST, port=cls.MONGODB_PORT)
            db = client[cls.DB_USER_TEMP]
            for coll_name in db.list_collection_names():
                if coll_name.startswith("system."):
                    continue
                coll = db[coll_name]
                indexes = coll.index_information()
                ttl_exists = any(
                    "expires_at" in [k for k, _ in info.get("key", [])]
                    and info.get("expireAfterSeconds") is not None
                    for info in indexes.values()
                )
                if not ttl_exists:
                    for name, info in list(indexes.items()):
                        if "expires_at" in [k for k, _ in info.get("key", [])]:
                            coll.drop_index(name)
                    coll.create_index("expires_at", expireAfterSeconds=0)
            client.close()
        except Exception:
            return

    @classmethod
    def cleanup_empty_temp_collections(cls) -> None:
        """Drop empty collections from User_Temp; drop the DB if none remain."""
        try:
            client = MongoClient(host=cls.MONGODB_HOST, port=cls.MONGODB_PORT)
            db = client[cls.DB_USER_TEMP]
            collections = [c for c in db.list_collection_names() if not c.startswith("system.")]
            for coll_name in collections:
                if db[coll_name].estimated_document_count() == 0:
                    db.drop_collection(coll_name)
            remaining = [c for c in db.list_collection_names() if not c.startswith("system.")]
            if not remaining:
                client.drop_database(cls.DB_USER_TEMP)
            client.close()
        except Exception:
            return


# ---------------------------------------------------------------------------
# Background cleanup thread (module-level — one thread for the process)
# ---------------------------------------------------------------------------

_cleanup_thread: Optional[threading.Thread] = None
_cleanup_stop_event = threading.Event()


def _cleanup_loop(interval_seconds: int = 60) -> None:
    while not _cleanup_stop_event.is_set():
        DatabaseConfig.cleanup_empty_temp_collections()
        _cleanup_stop_event.wait(timeout=interval_seconds)


def start_cleanup_thread(interval_seconds: int = 60) -> None:
    """Start the background temp-collection cleanup thread."""
    global _cleanup_thread
    _cleanup_stop_event.clear()
    _cleanup_thread = threading.Thread(
        target=_cleanup_loop,
        args=(interval_seconds,),
        daemon=True,
        name="temp-collection-cleanup",
    )
    _cleanup_thread.start()


def stop_cleanup_thread() -> None:
    """Signal the cleanup thread to stop and wait for it to exit."""
    _cleanup_stop_event.set()
    if _cleanup_thread and _cleanup_thread.is_alive():
        _cleanup_thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Application startup helper
# ---------------------------------------------------------------------------


def init_all_connections() -> None:
    """Connect to all databases, ensure TTL indexes, and start cleanup thread."""
    for env in ["development", "test", "uat", "production", "user_temp"]:
        DatabaseConfig.connect_to_db(env)

    for env in ["development", "test", "uat", "production"]:
        logs_alias = f"{env}_logs"
        connect(
            db=DatabaseConfig.get_logs_db_name(env),
            host=DatabaseConfig.MONGODB_HOST,
            port=DatabaseConfig.MONGODB_PORT,
            alias=logs_alias,
            uuidRepresentation="standard",
        )
        DatabaseConfig._connections[logs_alias] = logs_alias

    DatabaseConfig.ensure_ttl_indexes()
    start_cleanup_thread(interval_seconds=60)
