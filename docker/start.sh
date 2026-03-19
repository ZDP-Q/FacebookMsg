#!/bin/sh
# 确保在出错时立即退出
set -e

# 执行初始化/重置密码逻辑
echo "Running reset_pwd.py..."
python reset_pwd.py

# 使用 exec 启动主程序，使 Python 成为 PID 1 并能接收 SIGTERM 信号
echo "Starting application..."
exec python main.py
