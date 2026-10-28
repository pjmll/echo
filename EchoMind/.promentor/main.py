#!/usr/bin/env python3
"""
Mini EchoMind - 可运行入口

这是一个简化的多 Agent 客服系统演示，集成了前 6 章的所有组件：
- Ch1: 意图识别（三路融合投票）
- Ch2: 多 Agent 路由（domain_scores + routing_score）
- Ch3: MCP 工具框架（熔断器 + TTL 缓存 + 参数校验）
- Ch4: RAG 检索优化（分块 + 去重 + 重排）
- Ch5: 记忆与上下文构建（工作记忆 + 摘要 + 格式化）
- Ch6: 监控与路由降权（Z-score + penalty + 阈值告警）

使用方法：
    cd .promentor
    python main.py

进入交互模式后，输入消息即可看到完整的处理流程。
输入 'exit' 或 'quit' 退出。
输入 'stats' 查看系统统计。
"""
import sys
import os

# 添加各章目录到 Python 路径
CHAPTERS = [
    "ch01-intent",
    "ch02-routing",
    "ch03-mcp-tools",
    "ch04-rag",
    "ch05-memory-context",
    "ch06-monitoring",
    "final-assembly",
]

base_dir = os.path.dirname(os.path.abspath(__file__))
for chapter in CHAPTERS:
    chapter_path = os.path.join(base_dir, "chapters", chapter)
    if os.path.exists(chapter_path) and chapter_path not in sys.path:
        sys.path.insert(0, chapter_path)


def check_dependencies():
    """检查所有依赖模块是否已实现。"""
    required = {
        "intent_tools": "Ch1 意图识别",
        "routing": "Ch2 多 Agent 路由",
        "mcp_tools": "Ch3 MCP 工具框架",
        "rag_tools": "Ch4 RAG 检索优化",
        "memory_tools": "Ch5 记忆与上下文",
        "monitor_tools": "Ch6 监控与降权",
        "mini_echomind": "Final 组装",
    }

    missing = []
    for module, desc in required.items():
        try:
            __import__(module)
            print(f"  OK {desc} ({module})")
        except ImportError:
            print(f"  X  {desc} ({module}) - 未实现")
            missing.append(module)

    return missing


def main():
    print("=" * 60)
    print("Mini EchoMind - 多 Agent 客服系统演示")
    print("=" * 60)
    print()

    print("检查依赖模块...")
    missing = check_dependencies()
    print()

    if missing:
        print(f"错误：以下模块尚未实现：{', '.join(missing)}")
        print("请先完成对应章节的 Lab，再运行此演示。")
        print()
        print("章节顺序：")
        print("  1. /promentor learn ch01  → 实现 intent_tools.py")
        print("  2. /promentor learn ch02  → 实现 routing.py")
        print("  3. /promentor learn ch03  → 实现 mcp_tools.py")
        print("  4. /promentor learn ch04  → 实现 rag_tools.py")
        print("  5. /promentor learn ch05  → 实现 memory_tools.py")
        print("  6. /promentor learn ch06  → 实现 monitor_tools.py")
        print("  7. /promentor learn final → 实现 mini_echomind.py")
        return 1

    # 所有模块就绪，启动交互模式
    try:
        import mini_echomind
        system = mini_echomind.MiniEchoMind()
    except Exception as e:
        print(f"错误：初始化 MiniEchoMind 失败：{e}")
        return 1

    print("系统已启动！输入消息开始对话。")
    print("命令：")
    print("  exit/quit  - 退出")
    print("  stats      - 查看系统统计")
    print()

    user_id = "demo_user"
    conv_id = "demo_conv"

    while True:
        try:
            message = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not message:
            continue

        if message.lower() in ("exit", "quit"):
            print("再见！")
            break

        if message.lower() == "stats":
            stats = system.get_stats()
            print("\n系统统计：")
            for key, value in stats.items():
                print(f"  {key}: {value}")
            print()
            continue

        try:
            import asyncio
            response = asyncio.run(system.handle_request(user_id, conv_id, message))
            print(f"AI> {response}")
            print()
        except Exception as e:
            print(f"错误：处理请求失败：{e}")
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
