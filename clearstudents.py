import sqlite3
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))  # same as your app
DB_PATH = os.path.join(APP_DIR, "attendance.db")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Backup first (optional but strongly recommended)
c.execute("CREATE TABLE IF NOT EXISTS students_backup AS SELECT * FROM students")

# Delete all students
c.execute("DELETE FROM students")

conn.commit()
conn.close()

print("All students deleted successfully!")
