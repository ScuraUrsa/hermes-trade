"""Configuration system for HermesTrade.

Uses pydantic-settings for environment variable overrides with HERMES_TRADE_ prefix,
and supports loading from YAML configuration files.

Resolution order (last wins):
1. Default values defined in Settings model
2. YAML file values (if file exists)
3. Environment variables (HERMES_TRADE_ prefix)
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AlpacaConfig(BaseSettings):
    """Alpaca Markets broker configuration."""

    model_config = SettingsConfigDict(env_prefix="HERMES_TRADE_BROKERS__ALPACA__")

    api_key: str = ""
    secret_key: str = ""
    base_url: str = "https://paper-api.alpaca.markets"
    data_url: str = "https://data.alpaca.markets"


class IBKRConfig(BaseSettings):
    """Interactive Brokers configuration."""

    model_config = SettingsConfigDict(env_prefix="HERMES_TRADE_BROKERS__IBKR__")

    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1


class XTBConfig(BaseSettings):
    """XTB broker configuration."""

    model_config = SettingsConfigDict(env_prefix="HERMES_TRADE_BROKERS__XTB__")

    user_id: str = ""
    password: str = ""
    demo: bool = True


class BrokerConfig(BaseSettings):
    """Aggregate broker configuration."""

    model_config = SettingsConfigDict(env_prefix="HERMES_TRADE_BROKERS__")

    alpaca: AlpacaConfig = Field(default_factory=AlpacaConfig)
    ibkr: IBKRConfig = Field(default_factory=IBKRConfig)
    xtb: XTBConfig = Field(default_factory=XTBConfig)


class RiskLimitsConfig(BaseSettings):
    """Risk management limits configuration."""

    model_config = SettingsConfigDict(env_prefix="HERMES_TRADE_RISK__")

    max_position_size: Decimal = Field(default=Decimal("10000"), gt=0)
    max_daily_loss: Decimal = Field(default=Decimal("1000"), gt=0)
    max_drawdown_pct: float = Field(default=20.0, gt=0.0, le=100.0)
    max_trades_per_day: int = Field(default=50, gt=0)
    stop_loss_pct: float = Field(default=2.0, gt=0.0, le=100.0)
    take_profit_pct: float | None = Field(default=None, gt=0.0, le=1000.0)


class Settings(BaseSettings):
    """Top-level application settings.

    Reads from environment variables with HERMES_TRADE_ prefix,
    and can be initialised from a YAML configuration file.
    """

    model_config = SettingsConfigDict(
        env_prefix="HERMES_TRADE_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"
    brokers: BrokerConfig = Field(default_factory=BrokerConfig)
    risk: RiskLimitsConfig = Field(default_factory=RiskLimitsConfig)


def _load_yaml_values(yaml_path: str) -> dict[str, object]:
    """Load configuration values from a YAML file.

    Returns an empty dict if the file does not exist or cannot be parsed.
    """
    path = Path(yaml_path)
    if not path.is_file():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return {}
    return data


def _coerce_value(model: object, field_name: str, value: object) -> object:
    """Coerce a YAML value to match the pydantic field's expected type.

    YAML loads numbers as int/float and strings as str, but pydantic fields
    may expect Decimal, bool, etc. This handles the common coercions.
    """
    field_info = getattr(type(model), "model_fields", {}).get(field_name)
    if field_info is None:
        return value
    annotation = field_info.annotation
    # Handle Decimal fields (YAML loads as str or int)
    if annotation is Decimal:
        if isinstance(value, str):
            return Decimal(value)
        if isinstance(value, (int, float)):
            return Decimal(str(value))
    # Handle int fields (YAML may load as str)
    if annotation is int and isinstance(value, str):
        return int(value)
    # Handle float fields
    if annotation is float and isinstance(value, str):
        return float(value)
    # Handle bool fields (YAML loads as bool, but str from env-style)
    if annotation is bool and isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return value


def _merge_yaml_into_settings(settings: Settings, yaml_data: dict[str, object]) -> None:
    """Merge YAML values into a Settings instance, skipping env-overridden keys.

    Walks the nested YAML dict and sets attributes on the settings object,
    but only for keys that do NOT have a corresponding HERMES_TRADE_ env var set.
    This ensures env vars always take precedence over YAML.
    """
    env_prefix = "HERMES_TRADE_"

    def _walk(source: dict[str, object], target: object, prefix: str) -> None:
        for key, value in source.items():
            if isinstance(value, dict):
                _walk(value, getattr(target, key), f"{prefix}{key}__")
            else:
                # Build the env var name that would correspond to this key
                env_key = f"{env_prefix}{prefix}{key}".upper()
                if env_key not in os.environ:
                    coerced = _coerce_value(target, key, value)
                    setattr(target, key, coerced)

    _walk(yaml_data, settings, "")


def load_config(yaml_path: str | None = None) -> Settings:
    """Load configuration from a YAML file with environment variable overrides.

    Resolution order (last wins):
    1. Default values defined in Settings model
    2. YAML file values (if file exists)
    3. Environment variables (HERMES_TRADE_ prefix)

    Args:
        yaml_path: Path to YAML config file. Defaults to config/default.yaml
                   relative to the project root.

    Returns:
        A fully resolved Settings instance.
    """
    if yaml_path is None:
        # Default path: config/default.yaml relative to project root
        yaml_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config",
            "default.yaml",
        )

    # Create settings from env vars + defaults first
    settings = Settings()

    # Load YAML and merge values for keys not overridden by env
    yaml_data = _load_yaml_values(yaml_path)
    if yaml_data:
        _merge_yaml_into_settings(settings, yaml_data)

    return settings
