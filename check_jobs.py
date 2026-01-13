import sqlite3
import json

def check_history():
    conn = sqlite3.connect('video_platform.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, type, status, error_message, updated_at FROM jobs WHERE type IN ('caption', 'burn', 'split_scenes', 'split_fixed', 'trim') ORDER BY updated_at DESC LIMIT 20")
    rows = cursor.fetchall()
    print(f"{'TYPE':<15} | {'STATUS':<10} | {'ERROR'}")
    print("-" * 60)
    for row in rows:
        print(f"{row['type']:<15} | {row['status']:<10} | {row['error_message']}")
    conn.close()

if __name__ == "__main__":
    check_history()
