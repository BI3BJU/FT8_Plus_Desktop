# gui_theme.py - GUI 颜色常量与资源路径
import os
import sys

CONTACT_ALL = "All"

COLOR_BLACK   = "#000000"
COLOR_RED     = "#CC0000"
COLOR_MAROON  = "#800000"
COLOR_GREEN   = "#008000"
COLOR_BLUE    = "#0000FF"
COLOR_NAVY    = "#000080"
COLOR_INDIGO  = "#4B0082"
COLOR_YELLOW  = "#666600"
COLOR_TEAL    = "#006666"
COLOR_MAGENTA = "#CC00CC"
COLOR_GRAY    = "#666666"
COLOR_ORANGE  = "#993300"
COLOR_PINK    = "#C71585"
COLOR_PURPLE  = "#660066"
COLOR_BROWN   = "#A52A2A"
COLOR_WHITE   = "#FFFFFF"


def resource_path(relative_path):
    """兼容开发环境与 PyInstaller 的资源定位。"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), relative_path)
    return os.path.join(os.path.abspath("."), relative_path)
