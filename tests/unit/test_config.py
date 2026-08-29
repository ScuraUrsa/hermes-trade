"""Tests for configuration system — Settings, YAML loader, env overrides."""

from decimal import Decimal

import pytest
import yaml
from pydantic import ValidationError

from hermes_trade.core.config import (
    AlpacaConfig,
    BrokerConfig,
    IBKRConfig,
    RiskLimitsConfig,
    Settings,
    XTBConfig,
    load_config,
)


class TestAlpacaConfig:
    """Tests for Alpaca broker configuration model."""

    def test_defaults(self) -> None:
        cfg = AlpacaConfig()
        assert cfg.api_key == ""
        assert cfg.secret_key == ""
        assert cfg.base_url == "https://paper-api.alpaca.markets"
        assert cfg.data_url == "https://data.alpaca.markets"

    def test_custom_values(self) -> None:
        cfg = AlpacaConfig(api_key="PK_TEST", secret_key="SK_TEST")
        assert cfg.api_key == "PK_TEST"
        assert cfg.secret_key == "SK_TEST"

    def test_custom_urls(self) -> None:
        cfg = AlpacaConfig(
            base_url="https://api.alpaca.markets",
            data_url="https://data.alpaca.markets/v2",
        )
        assert cfg.base_url == "https://api.alpaca.markets"


class TestIBKRConfig:
    """Tests for Interactive Brokers configuration model."""

    def test_defaults(self) -> None:
        cfg = IBKRConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 7497
        assert cfg.client_id == 1

    def test_custom_values(self) -> None:
        cfg = IBKRConfig(host="192.168.1.100", port=7496, client_id=99)
        assert cfg.host == "192.168.1.100"
        assert cfg.port == 7496
        assert cfg.client_id == 99


class TestXTBConfig:
    """Tests for XTB broker configuration model."""

    def test_defaults(self) -> None:
        cfg = XTBConfig()
        assert cfg.user_id == ""
        assert cfg.password == ""
        assert cfg.demo is True

    def test_custom_values(self) -> None:
        cfg = XTBConfig(user_id="12345", password="secret", demo=False)
        assert cfg.user_id == "12345"
        assert cfg.password == "secret"
        assert cfg.demo is False


class TestBrokerConfig:
    """Tests for the aggregate broker configuration."""

    def test_defaults(self) -> None:
        cfg = BrokerConfig()
        assert isinstance(cfg.alpaca, AlpacaConfig)
        assert isinstance(cfg.ibkr, IBKRConfig)
        assert isinstance(cfg.xtb, XTBConfig)
        assert cfg.alpaca.base_url == "https://paper-api.alpaca.markets"
        assert cfg.ibkr.host == "127.0.0.1"
        assert cfg.xtb.demo is True

    def test_nested_customisation(self) -> None:
        cfg = BrokerConfig(
            alpaca=AlpacaConfig(api_key="key1"),
            ibkr=IBKRConfig(port=4001),
        )
        assert cfg.alpaca.api_key == "key1"
        assert cfg.ibkr.port == 4001


class TestRiskLimitsConfig:
    """Tests for risk limits configuration model."""

    def test_defaults(self) -> None:
        cfg = RiskLimitsConfig()
        assert cfg.max_position_size == Decimal("10000")
        assert cfg.max_daily_loss == Decimal("1000")
        assert cfg.max_drawdown_pct == 20.0
        assert cfg.max_trades_per_day == 50
        assert cfg.stop_loss_pct == 2.0
        assert cfg.take_profit_pct is None

    def test_custom_values(self) -> None:
        cfg = RiskLimitsConfig(
            max_position_size=Decimal("5000"),
            max_daily_loss=Decimal("500"),
            max_drawdown_pct=15.0,
            max_trades_per_day=25,
            stop_loss_pct=1.5,
            take_profit_pct=5.0,
        )
        assert cfg.max_position_size == Decimal("5000")
        assert cfg.max_daily_loss == Decimal("500")
        assert cfg.max_drawdown_pct == 15.0
        assert cfg.max_trades_per_day == 25
        assert cfg.stop_loss_pct == 1.5
        assert cfg.take_profit_pct == 5.0

    def test_rejects_negative_max_position_size(self) -> None:
        with pytest.raises(ValidationError):
            RiskLimitsConfig(max_position_size=Decimal("-1"))

    def test_rejects_zero_max_trades_per_day(self) -> None:
        with pytest.raises(ValidationError):
            RiskLimitsConfig(max_trades_per_day=0)


class TestSettingsDefaults:
    """Tests for top-level Settings with default values (no YAML, no env)."""

    def test_default_redis_url(self) -> None:
        settings = Settings()
        assert settings.redis_url == "redis://localhost:6379/0"

    def test_default_log_level(self) -> None:
        settings = Settings()
        assert settings.log_level == "INFO"

    def test_default_brokers(self) -> None:
        settings = Settings()
        assert settings.brokers.alpaca.base_url == "https://paper-api.alpaca.markets"
        assert settings.brokers.ibkr.port == 7497
        assert settings.brokers.xtb.demo is True

    def test_default_risk_limits(self) -> None:
        settings = Settings()
        assert settings.risk.max_position_size == Decimal("10000")
        assert settings.risk.stop_loss_pct == 2.0


class TestSettingsEnvOverrides:
    """Tests for environment variable overrides with HERMES_TRADE_ prefix."""

    def test_env_override_redis_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HERMES_TRADE_REDIS_URL", "redis://prod:6379/1")
        settings = Settings()
        assert settings.redis_url == "redis://prod:6379/1"

    def test_env_override_log_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HERMES_TRADE_LOG_LEVEL", "DEBUG")
        settings = Settings()
        assert settings.log_level == "DEBUG"

    def test_env_override_nested_alpaca_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HERMES_TRADE_BROKERS__ALPACA__API_KEY", "PK_ENV_OVERRIDE")
        settings = Settings()
        assert settings.brokers.alpaca.api_key == "PK_ENV_OVERRIDE"

    def test_env_override_nested_ibkr_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HERMES_TRADE_BROKERS__IBKR__PORT", "4001")
        settings = Settings()
        assert settings.brokers.ibkr.port == 4001

    def test_env_override_nested_xtb_demo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HERMES_TRADE_BROKERS__XTB__DEMO", "false")
        settings = Settings()
        assert settings.brokers.xtb.demo is False

    def test_env_override_risk_max_position_size(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HERMES_TRADE_RISK__MAX_POSITION_SIZE", "5000")
        settings = Settings()
        assert settings.risk.max_position_size == Decimal("5000")

    def test_env_override_risk_stop_loss_pct(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HERMES_TRADE_RISK__STOP_LOSS_PCT", "3.5")
        settings = Settings()
        assert settings.risk.stop_loss_pct == 3.5

    def test_env_override_multiple_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HERMES_TRADE_REDIS_URL", "redis://multi:6379/3")
        monkeypatch.setenv("HERMES_TRADE_LOG_LEVEL", "WARNING")
        monkeypatch.setenv("HERMES_TRADE_RISK__MAX_TRADES_PER_DAY", "100")
        settings = Settings()
        assert settings.redis_url == "redis://multi:6379/3"
        assert settings.log_level == "WARNING"
        assert settings.risk.max_trades_per_day == 100


class TestLoadConfig:
    """Tests for the load_config helper that reads YAML files."""

    def test_load_from_yaml_file(self, tmp_path: str) -> None:
        yaml_content = {
            "redis_url": "redis://custom:6380/2",
            "log_level": "WARNING",
            "brokers": {
                "alpaca": {
                    "api_key": "yaml_key",
                    "secret_key": "yaml_secret",
                },
            },
            "risk": {
                "max_position_size": "20000",
                "max_daily_loss": "2000",
            },
        }
        yaml_path = tmp_path / "test_config.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(yaml_content, f)

        settings = load_config(str(yaml_path))
        assert settings.redis_url == "redis://custom:6380/2"
        assert settings.log_level == "WARNING"
        assert settings.brokers.alpaca.api_key == "yaml_key"
        assert settings.brokers.alpaca.secret_key == "yaml_secret"
        assert settings.risk.max_position_size == Decimal("20000")
        assert settings.risk.max_daily_loss == Decimal("2000")

    def test_yaml_with_env_override(
        self, tmp_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        yaml_content = {
            "redis_url": "redis://yaml:6379/0",
            "log_level": "INFO",
        }
        yaml_path = tmp_path / "test_config.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(yaml_content, f)

        monkeypatch.setenv("HERMES_TRADE_REDIS_URL", "redis://env:6379/1")
        monkeypatch.setenv("HERMES_TRADE_LOG_LEVEL", "ERROR")

        settings = load_config(str(yaml_path))
        # Env vars should take precedence over YAML values
        assert settings.redis_url == "redis://env:6379/1"
        assert settings.log_level == "ERROR"

    def test_yaml_partial_override_keeps_defaults(
        self, tmp_path: str
    ) -> None:
        """YAML with only some fields set; defaults fill the rest."""
        yaml_content = {
            "redis_url": "redis://partial:6379/0",
        }
        yaml_path = tmp_path / "test_config.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(yaml_content, f)

        settings = load_config(str(yaml_path))
        assert settings.redis_url == "redis://partial:6379/0"
        # These should still be defaults
        assert settings.log_level == "INFO"
        assert settings.brokers.alpaca.base_url == "https://paper-api.alpaca.markets"
        assert settings.risk.max_position_size == Decimal("10000")

    def test_load_missing_yaml_file_falls_back_to_defaults(self) -> None:
        """Loading a non-existent YAML file should not crash; use defaults."""
        settings = load_config("/nonexistent/path/config.yaml")
        assert settings.redis_url == "redis://localhost:6379/0"
        assert settings.log_level == "INFO"

    def test_load_config_default_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """load_config() with no args uses config/default.yaml if it exists."""
        # We can't easily test the default path without the real file,
        # but we can verify the function signature and that it returns Settings.
        settings = load_config()
        assert isinstance(settings, Settings)
