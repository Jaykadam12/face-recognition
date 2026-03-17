import sqlite3

conn = sqlite3.connect("attendance.db")
c = conn.cursor()

c.execute("UPDATE students SET class='TE' WHERE id=1")

conn.commit()
conn.close()

print("Updated successfully")