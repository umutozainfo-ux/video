import sqlite3

def debug():
    conn = sqlite3.connect('video_platform.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    print("Tables:", cursor.fetchall())
    
    cursor.execute("SELECT COUNT(*) FROM jobs")
    print("Total jobs:", cursor.fetchone()[0])
    
    cursor.execute("SELECT id, status, type FROM jobs LIMIT 5")
    print("Recent jobs:", cursor.fetchall())
    conn.close()

if __name__ == "__main__":
    debug()
