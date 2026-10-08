# gui.py - 组装入口（GUI = 各 mixin 组合）
from gui_base import GuiBase
from gui_callbacks import CallbacksMixin
from gui_builder import BuilderMixin
from gui_tx_input import TxInputMixin
from gui_history_view import HistoryViewMixin
from gui_log_view import LogViewMixin


class GUI(CallbacksMixin, BuilderMixin, TxInputMixin, HistoryViewMixin,
          LogViewMixin, GuiBase):
    """FT8 Plus GUI。功能分布在各个 mixin 中。"""
    pass


__all__ = ["GUI"]
