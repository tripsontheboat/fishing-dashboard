import sqlite3
from werkzeug.security import generate_password_hash

username = "browndawg29"      # change if you want
password = "yourpassword"     # change this!
role = "admin"

conn = sqlite3.connect("mydatabase.db")
cursor = conn.cursor()

hashed = generate_password_hash(password, method="pbkdf2:sha256")

cursor.execute(
    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
    (username, hashed, role)
)

conn.commit()
conn.close()

print("Admin user created successfully!")

