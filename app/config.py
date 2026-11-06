"""Validated, version-controlled source definitions."""
import json
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "sources.json"


class SourceDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    format: Literal["cidr_text", "ip_text", "json"]
    json_path: str | None = None
    enabled: bool = True
    refresh_interval_minutes: int | None = Field(default=None, ge=1, le=10080)

    @model_validator(mode="after")
    def validate_feed(self):
        if self.url.scheme != "https" or self.url.username or self.url.password:
            raise ValueError("Source URL must use HTTPS without credentials")
        if self.format == "json" and not self.json_path:
            raise ValueError("JSON feeds require json_path")
        if self.json_path and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", self.json_path):
            raise ValueError("Invalid JSON path")
        return self


class SourceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[SourceDefinition]


def load_source_config(path=None):
    path = Path(path or os.environ.get("BOOSTER_SOURCES_CONFIG", DEFAULT_CONFIG_PATH))
    config = SourceFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    ids = [source.id for source in config.sources]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source IDs in " + str(path))
    return config.sources
