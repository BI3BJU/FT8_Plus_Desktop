# core.py - 组装入口（Core = 各 mixin 组合）
from core_base import CoreBase, StdoutRedirector
from core_time import TimeMixin
from core_config import ConfigMixin
from core_receiver import ReceiverMixin
from core_beacon import BeaconMixin
from core_tx import TxMixin
from core_rx import RxMixin
from core_contacts import ContactsMixin
from core_history import HistoryMixin


class Core(TimeMixin, ConfigMixin, ReceiverMixin, BeaconMixin,
           TxMixin, RxMixin, ContactsMixin, HistoryMixin, CoreBase):
    """FT8 Plus 业务核心。功能分布在各个 mixin 中。"""
    pass


__all__ = ["Core", "StdoutRedirector"]
