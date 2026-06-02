from langchain_core.tools import tool
@tool
def get_weather(city: str) -> str:
    """获取指定城市的天气"""
    return f"【工具调用成功】{city} 今天晴天，25℃"