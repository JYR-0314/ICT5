# -*- coding: utf-8 -*-
"""应用配置：可通过环境变量 / .env 覆盖。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on", "y"}


@dataclass
class Settings:
    # ---- 路径 ----
    base_dir: Path = BASE_DIR
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DSH_DATA_DIR", str(BASE_DIR / "data"))))
    upload_dir: Path = None  # 由 __post_init__ 初始化
    db_path: Path = None

    # ---- 数据库 ----
    database_url: str = os.getenv("DATABASE_URL", "")

    # ---- 提取引擎 ----
    # 可选值: rule(规则引擎,默认,无需联网) | llm(大模型引擎,需配置 API) | hybrid
    extraction_engine: str = os.getenv("EXTRACTION_ENGINE", "rule")

    # OpenAI 兼容的大模型 API(Qwen/DeepSeek 等国产模型)
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "qwen-plus")
    llm_timeout: int = int(os.getenv("LLM_TIMEOUT", "120"))

    # ---- 服务 ----
    host: str = os.getenv("DSH_HOST", "0.0.0.0")
    port: int = int(os.getenv("DSH_PORT", "8000"))
    reload: bool = _env_bool("DSH_RELOAD", False)

    # 附件解析: 是否尝试调用 LibreOffice 解析 .doc
    libreoffice_path: str = os.getenv("LIBREOFFICE_PATH", "soffice")

    def __post_init__(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir = self.data_dir / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.db_path = self.data_dir / "dsh.db"
            self.database_url = f"sqlite:///{self.db_path.as_posix()}"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key) and self.extraction_engine in {"llm", "hybrid"}


settings = Settings()
