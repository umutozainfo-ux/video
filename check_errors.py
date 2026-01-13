import sqlite3
import json

def check_recent_failures():
    conn = sqlite3.connect('video_platform.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # Check jobs that were updated recently
    cursor.execute("SELECT id, type, status, error_message, updated_at FROM jobs ORDER BY updated_at DESC LIMIT 10")
    rows = cursor.fetchall()
    for row in rows:
        print(f"ID: {row['id']} | Status: {row['status']} | Updated: {row['updated_at']}")
        if row['error_message']:
            print(f"Error: {row['error_message']}")
        print("-" * 20)
    conn.close()

if __name__ == "__main__":
    check_recent_failures()
