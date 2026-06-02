from .get_weather import get_weather
from .total import add

# 所有工具的注册表
_TOOL_REGISTRY = [
    get_weather,
    add,
]


def get_all_tools():
    """返回所有已注册的工具列表"""
    return _TOOL_REGISTRY.copy()