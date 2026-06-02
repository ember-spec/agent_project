from langchain_core.tools import tool
@tool
def add(a:int, b:int) -> int:
    """计算a和b的和"""
    return a + b