"""
Configuration management with validation and safety checks.

This module handles loading and validating all system configuration,
including enforcing hard-coded safety limits that cannot be overridden.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
import os
from pydantic import BaseModel, Field, validator


class TradingConfig(BaseModel):
    """Trading configuration with validation."""
    mode: str = Field(..., pattern="^(paper|live)$")
    default_exchange: str
    default_segment: str
    default_product: str
    order_validity: str = "DAY"

    @validator('mode')
    def validate_mode(cls, v):
        """Always start in paper mode for safety if FORCE_PAPER_MODE is set."""
        force_paper = os.getenv('FORCE_PAPER_MODE', '1')
        if force_paper == '1':
            if v == 'live':
                raise ValueError(
                    "FORCE_PAPER_MODE=1 prevents live trading. "
                    "Set FORCE_PAPER_MODE=0 in environment to enable live mode "
                    "(only after extensive testing and approval)."
                )
            return 'paper'
        return v


class RiskConfig(BaseModel):
    """Risk management configuration with bounds."""
    max_portfolio_value: int = Field(..., gt=0)
    max_position_size: int = Field(..., gt=0)
    max_daily_loss: int = Field(..., gt=0)
    max_open_positions: int = Field(..., gt=0)
    position_size_pct: float = Field(..., ge=0, le=1)
    stop_loss_pct: float = Field(..., ge=0, le=1)
    take_profit_pct: float = Field(..., ge=0, le=1)


class RateLimitsConfig(BaseModel):
    """API rate limits configuration."""
    orders_per_second: int = Field(..., gt=0, le=15)
    live_data_per_second: int = Field(..., gt=0, le=10)
    non_trading_per_second: int = Field(..., gt=0, le=20)


class HardLimits(BaseModel):
    """Non-overridable safety limits from trading_limits.yaml."""
    MAX_SINGLE_ORDER_VALUE: int
    MAX_DAILY_ORDERS: int
    MAX_PORTFOLIO_VALUE: int
    MAX_DAILY_LOSS_HARD: int
    MIN_ACCOUNT_BALANCE: int
    ALLOWED_EXCHANGES: List[str]
    FORBIDDEN_SEGMENTS: List[str]
    FORBIDDEN_PRODUCTS: List[str]


class KillSwitchCondition(BaseModel):
    """Kill switch condition definition."""
    type: str
    description: str


class RecoveryProtocol(BaseModel):
    """Recovery protocol after kill switch activation."""
    require_manual_restart: bool
    require_admin_approval: bool
    cooldown_period_minutes: int
    approval_code: str
    actions_on_activation: List[str]
    restart_checklist: List[str]


class Config:
    """
    Main configuration manager.

    Responsibilities:
    - Load default configuration
    - Merge local overrides
    - Enforce hard limits
    - Validate all settings
    - Provide easy access to config values
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize configuration manager.

        Args:
            config_path: Optional path to custom config file
        """
        # Determine project root (4 levels up from this file)
        self.project_root = Path(__file__).parent.parent.parent.parent
        self.config_dir = self.project_root / "config"

        # Configuration file paths
        self.default_config_path = self.config_dir / "default_config.yaml"
        self.local_config_path = self.config_dir / "config.local.yaml"
        self.limits_path = self.config_dir / "trading_limits.yaml"

        # Override default config path if provided
        if config_path:
            self.default_config_path = config_path

        self._config: Dict[str, Any] = {}
        self._hard_limits: Optional[HardLimits] = None
        self._kill_switch_conditions: List[KillSwitchCondition] = []
        self._recovery_protocol: Optional[RecoveryProtocol] = None

        self.load()

    def load(self) -> None:
        """Load and validate all configuration files."""
        # Load default configuration
        if not self.default_config_path.exists():
            raise FileNotFoundError(
                f"Default configuration not found: {self.default_config_path}"
            )

        with open(self.default_config_path, encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

        # Merge local configuration if it exists
        if self.local_config_path.exists():
            with open(self.local_config_path, encoding='utf-8') as f:
                local = yaml.safe_load(f)
                if local:
                    self._deep_merge(self._config, local)

        # Load hard limits (cannot be overridden)
        if not self.limits_path.exists():
            raise FileNotFoundError(
                f"Trading limits file not found: {self.limits_path}"
            )

        with open(self.limits_path, encoding='utf-8') as f:
            limits_data = yaml.safe_load(f)
            self._hard_limits = HardLimits(**limits_data['ABSOLUTE_LIMITS'])

            # Load kill switch conditions
            if 'KILL_SWITCH_CONDITIONS' in limits_data:
                self._kill_switch_conditions = [
                    KillSwitchCondition(**cond)
                    for cond in limits_data['KILL_SWITCH_CONDITIONS']
                ]

            # Load recovery protocol
            if 'RECOVERY_PROTOCOL' in limits_data:
                self._recovery_protocol = RecoveryProtocol(
                    **limits_data['RECOVERY_PROTOCOL']
                )

        # Validate configuration against hard limits
        self._validate_limits()

        # Validate trading configuration
        self._validate_trading_config()

    def _deep_merge(self, base: dict, override: dict) -> None:
        """
        Deep merge override dict into base dict.

        Args:
            base: Base dictionary to merge into
            override: Dictionary with override values
        """
        for key, value in override.items():
            if (key in base and
                isinstance(base[key], dict) and
                isinstance(value, dict)):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def _validate_limits(self) -> None:
        """Ensure configuration doesn't exceed hard limits."""
        risk = self._config.get('risk', {})

        # Validate portfolio value
        max_portfolio = risk.get('max_portfolio_value', 0)
        if max_portfolio > self._hard_limits.MAX_PORTFOLIO_VALUE:
            raise ValueError(
                f"max_portfolio_value ({max_portfolio}) exceeds hard limit "
                f"({self._hard_limits.MAX_PORTFOLIO_VALUE})"
            )

        # Validate position size
        max_position = risk.get('max_position_size', 0)
        if max_position > self._hard_limits.MAX_SINGLE_ORDER_VALUE:
            raise ValueError(
                f"max_position_size ({max_position}) exceeds hard limit "
                f"({self._hard_limits.MAX_SINGLE_ORDER_VALUE})"
            )

        # Validate daily loss limit
        max_daily_loss = risk.get('max_daily_loss', 0)
        if max_daily_loss > self._hard_limits.MAX_DAILY_LOSS_HARD:
            raise ValueError(
                f"max_daily_loss ({max_daily_loss}) exceeds hard limit "
                f"({self._hard_limits.MAX_DAILY_LOSS_HARD})"
            )

    def _validate_trading_config(self) -> None:
        """Validate trading configuration."""
        trading = self._config.get('trading', {})

        # Validate exchange
        exchange = trading.get('default_exchange')
        if exchange not in self._hard_limits.ALLOWED_EXCHANGES:
            raise ValueError(
                f"Exchange {exchange} not in allowed exchanges: "
                f"{self._hard_limits.ALLOWED_EXCHANGES}"
            )

        # Validate segment
        segment = trading.get('default_segment')
        if segment in self._hard_limits.FORBIDDEN_SEGMENTS:
            raise ValueError(
                f"Segment {segment} is forbidden by hard limits"
            )

        # Validate product
        product = trading.get('default_product')
        if product in self._hard_limits.FORBIDDEN_PRODUCTS:
            raise ValueError(
                f"Product {product} is forbidden by hard limits"
            )

        # Validate trading mode
        TradingConfig(**trading)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.

        Args:
            key: Configuration key in dot notation (e.g., 'risk.max_portfolio_value')
            default: Default value if key not found

        Returns:
            Configuration value or default

        Example:
            >>> config.get('risk.max_portfolio_value')
            50000
            >>> config.get('nonexistent.key', 'default')
            'default'
        """
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """
        Set configuration value (runtime only, not persisted).

        Args:
            key: Configuration key in dot notation
            value: Value to set

        Note:
            This only modifies the in-memory configuration.
            Changes are not persisted to disk.
        """
        keys = key.split('.')
        config = self._config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value

        # Re-validate after change
        self._validate_limits()

    @property
    def hard_limits(self) -> HardLimits:
        """Get hard limits (read-only)."""
        return self._hard_limits

    @property
    def kill_switch_conditions(self) -> List[KillSwitchCondition]:
        """Get kill switch conditions (read-only)."""
        return self._kill_switch_conditions

    @property
    def recovery_protocol(self) -> RecoveryProtocol:
        """Get recovery protocol (read-only)."""
        return self._recovery_protocol

    def is_paper_mode(self) -> bool:
        """
        Check if running in paper trading mode.

        Returns:
            True if paper mode, False if live trading
        """
        return self.get('trading.mode') == 'paper'

    def is_production(self) -> bool:
        """
        Check if running in production environment.

        Returns:
            True if production, False otherwise
        """
        return self.get('app.environment') == 'production'

    def get_data_dir(self) -> Path:
        """Get data directory path."""
        return self.project_root / "data"

    def get_log_dir(self) -> Path:
        """Get log directory path."""
        log_dir = self.get('logging.log_dir', 'data/logs')
        return self.project_root / log_dir

    def get_cache_dir(self) -> Path:
        """Get cache directory path."""
        cache_dir = self.get('data.cache_dir', 'data/cache')
        return self.project_root / cache_dir

    def validate_order_params(
        self,
        symbol: str,
        exchange: str,
        segment: str,
        product: str,
        order_value: float
    ) -> tuple[bool, Optional[str]]:
        """
        Validate order parameters against hard limits.

        Args:
            symbol: Stock symbol
            exchange: Exchange (NSE/BSE)
            segment: Market segment (CASH/FNO)
            product: Product type (CNC/MIS/NRML)
            order_value: Total order value in INR

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check exchange
        if exchange not in self._hard_limits.ALLOWED_EXCHANGES:
            return False, f"Exchange {exchange} not allowed"

        # Check segment
        if segment in self._hard_limits.FORBIDDEN_SEGMENTS:
            return False, f"Segment {segment} is forbidden"

        # Check product
        if product in self._hard_limits.FORBIDDEN_PRODUCTS:
            return False, f"Product {product} is forbidden"

        # Check order value
        if order_value > self._hard_limits.MAX_SINGLE_ORDER_VALUE:
            return False, (
                f"Order value {order_value:.2f} exceeds limit "
                f"{self._hard_limits.MAX_SINGLE_ORDER_VALUE}"
            )

        return True, None

    def to_dict(self) -> dict:
        """
        Export configuration as dictionary.

        Returns:
            Dictionary with all configuration
        """
        return {
            'config': self._config,
            'hard_limits': self._hard_limits.dict() if self._hard_limits else None,
            'kill_switch_conditions': [
                c.dict() for c in self._kill_switch_conditions
            ],
            'recovery_protocol': (
                self._recovery_protocol.dict() if self._recovery_protocol else None
            )
        }


# Singleton instance
_config_instance: Optional[Config] = None
_config_lock = False


def get_config() -> Config:
    """
    Get global configuration instance (singleton).

    Returns:
        Config: Global configuration instance

    Example:
        >>> config = get_config()
        >>> print(config.get('trading.mode'))
        paper
    """
    global _config_instance, _config_lock

    if _config_instance is None:
        if _config_lock:
            raise RuntimeError("Configuration is being initialized")

        _config_lock = True
        try:
            _config_instance = Config()
        finally:
            _config_lock = False

    return _config_instance


def reload_config() -> Config:
    """
    Reload configuration from files.

    Returns:
        Config: Reloaded configuration instance

    Warning:
        This will reload all configuration and re-validate.
        Use with caution in production.
    """
    global _config_instance
    _config_instance = None
    return get_config()
