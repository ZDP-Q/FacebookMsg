import os
import sqlite3
from pathlib import Path
from app.security import hash_password, generate_salt, PBKDF2_ITERATIONS, is_strong_password
from app.database import init_db

# 数据库路径
DB_PATH = Path("data/facebookmsg.sqlite3")

def reset_password():
    password = os.getenv("ADMIN_PASSWORD", "").strip()
    
    if not password:
        print("错误: 请先设置环境变量 ADMIN_PASSWORD")
        return

    if not is_strong_password(password):
        print("错误: 密码强度不足（需16位以上，含大小写字母、数字和特殊字符）")
        return

    # 如果数据库不存在，先初始化
    if not DB_PATH.exists():
        print(f"提示: 数据库不存在，正在初始化 {DB_PATH}...")
        init_db()

    salt = generate_salt()
    pw_hash = hash_password(password, salt, PBKDF2_ITERATIONS)

    conn = sqlite3.connect(DB_PATH)
    try:
        # 更新管理员账号 (id=1)
        # 确保表中至少有一条记录，否则 UPDATE 无效
        cursor = conn.execute("SELECT id FROM admin_auth WHERE id = 1")
        if not cursor.fetchone():
            print("提示: 插入初始管理员记录...")
            conn.execute("""
                INSERT INTO admin_auth (id, username, password_hash, password_salt, password_iterations)
                VALUES (1, 'admin', 'tmp', 'tmp', ?)
            """, (PBKDF2_ITERATIONS,))

        conn.execute("""
            UPDATE admin_auth 
            SET password_hash = ?, 
                password_salt = ?, 
                password_iterations = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        """, (pw_hash, salt, PBKDF2_ITERATIONS))
        
        # 成功重置密码后，清空所有登录尝试和锁定记录
        conn.execute("DELETE FROM admin_login_attempts")
        
        conn.commit()
        print("成功: 管理员密码已重置，登录锁定已解除！")
    except Exception as e:
        print(f"失败: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    reset_password()
