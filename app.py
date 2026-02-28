import os
import sqlite3
from flask import Flask, render_template, request, redirect, abort
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
    UserMixin
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "static/uploads"
app.config["SECRET_KEY"] = "super-secret-key"

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


# -----------------------------
# USER + AUTH SETUP
# -----------------------------
def get_user_connection():
    conn = sqlite3.connect("mydatabase.db")
    conn.row_factory = sqlite3.Row
    return conn


class User(UserMixin):
    def __init__(self, id, username, password_hash, role):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.role = role

    @staticmethod
    def get(user_id):
        conn = get_user_connection()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        if row:
            return User(row["id"], row["username"], row["password_hash"], row["role"])
        return None

    @staticmethod
    def find_by_username(username):
        conn = get_user_connection()
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if row:
            return User(row["id"], row["username"], row["password_hash"], row["role"])
        return None

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# -----------------------------
# LOGIN MANAGER
# -----------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)


# -----------------------------
# ROLE DECORATOR
# -----------------------------
def role_required(role):
    def wrapper(fn):
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role not in [role, "admin"]:
                abort(403)
            return fn(*args, **kwargs)
        decorated_view.__name__ = fn.__name__
        return decorated_view
    return wrapper


# -----------------------------
# OBSERVATION DB CONNECTION
# -----------------------------
def get_db_connection():
    conn = sqlite3.connect("mydatabase.db")
    conn.row_factory = sqlite3.Row
    return conn


# -----------------------------
# LOGIN
# -----------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.find_by_username(username)
        if user and user.check_password(password):
            login_user(user)
            return redirect("/")
        return "Invalid username or password"

    return render_template("login.html")


# -----------------------------
# LOGOUT
# -----------------------------
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/login")


# -----------------------------
# HOME PAGE
# -----------------------------
@app.route("/")
@login_required
@role_required("read")
def index():
    start = request.args.get("start")
    end = request.args.get("end")
    sort = request.args.get("sort", "newest")
    species_filter = request.args.get("species")

    query = "SELECT * FROM observations WHERE 1=1"
    params = []

    if start:
        query += " AND DATE(date) >= DATE(?)"
        params.append(start)

    if end:
        query += " AND DATE(date) <= DATE(?)"
        params.append(end)

    if species_filter and species_filter != "all":
        query += " AND species = ?"
        params.append(species_filter)

    if sort == "oldest":
        query += " ORDER BY DATE(date) ASC"
    else:
        query += " ORDER BY DATE(date) DESC"

    conn = get_db_connection()

    species_raw = conn.execute(
        "SELECT DISTINCT species FROM observations ORDER BY species ASC"
    ).fetchall()
    species_list = [dict(s) for s in species_raw]

    rows_raw = conn.execute(query, params).fetchall()
    rows = [dict(r) for r in rows_raw]

    total_trips = len(rows)
    total_fish = 0
    species_counts = {}

    for r in rows:
        try:
            total_fish += int(r["count"]) if r["count"] else 0
        except:
            pass

        sp = r["species"]
        if sp:
            species_counts[sp] = species_counts.get(sp, 0) + 1

    most_common_species = None
    if species_counts:
        most_common_species = max(species_counts, key=species_counts.get)

    conn.close()

    return render_template(
        "index.html",
        data=rows,
        species_list=species_list,
        total_trips=total_trips,
        total_fish=total_fish,
        most_common_species=most_common_species
    )


# -----------------------------
# REPORT PAGE
# -----------------------------
@app.route("/report", methods=["GET"])
@login_required
@role_required("read")
def report():
    start = request.args.get("start")
    end = request.args.get("end")
    species = request.args.get("species")
    location = request.args.get("location")
    water = request.args.get("water")
    platform = request.args.get("platform")

    query = "SELECT * FROM observations WHERE 1=1"
    params = []

    if start:
        query += " AND DATE(date) >= DATE(?)"
        params.append(start)

    if end:
        query += " AND DATE(date) <= DATE(?)"
        params.append(end)

    if species:
        query += " AND species LIKE ?"
        params.append(f"%{species}%")

    if location:
        query += " AND location LIKE ?"
        params.append(f"%{location}%")

    if water:
        query += " AND water LIKE ?"
        params.append(f"%{water}%")

    if platform:
        query += " AND platform LIKE ?"
        params.append(f"%{platform}%")

    conn = get_db_connection()
    rows_raw = conn.execute(query, params).fetchall()
    rows = [dict(r) for r in rows_raw]
    conn.close()

    return render_template("report.html", rows=rows)


# -----------------------------
# ADD ENTRY
# -----------------------------
@app.route("/add", methods=["GET", "POST"])
@login_required
@role_required("write")
def add():
    if request.method == "POST":
        date = request.form["date"]
        location = request.form["location"]
        species = request.form["species"]
        count = request.form["count"]
        bait = request.form["bait"]
        size = request.form["size"]
        water = request.form["water"]
        platform = request.form["platform"]
        comments = request.form["comments"]

        lat = request.form.get("lat")
        lng = request.form.get("lng")

        image_file = request.files["image"]
        filename = None

        if image_file and image_file.filename != "":
            filename = image_file.filename
            image_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            image_file.save(image_path)

        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO observations 
            (date, location, species, count, bait, size, water, platform, comments, image, lat, lng)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (date, location, species, count, bait, size, water, platform, comments, filename, lat, lng),
        )
        conn.commit()
        conn.close()

        return redirect("/")

    return render_template("add.html")


# -----------------------------
# CREATE USER (ADMIN ONLY)
# -----------------------------
@app.route("/create_user", methods=["GET", "POST"])
@login_required
def create_user():
    if current_user.role != "admin":
        return "Access denied", 403

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        role = request.form["role"]

        hashed_pw = generate_password_hash(password)

        conn = get_user_connection()
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, hashed_pw, role)
        )
        conn.commit()
        conn.close()

        return redirect("/")

    return render_template("create_user.html")


# -----------------------------
# EDIT ENTRY
# -----------------------------
@app.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
@role_required("write")
def edit(id):
    conn = get_db_connection()
    record = conn.execute("SELECT * FROM observations WHERE id = ?", (id,)).fetchone()

    if request.method == "POST":
        date = request.form["date"]
        location = request.form["location"]
        species = request.form["species"]
        count = request.form["count"]
        bait = request.form["bait"]
        size = request.form["size"]
        water = request.form["water"]
        platform = request.form["platform"]
        comments = request.form["comments"]

        lat = request.form.get("lat")
        lng = request.form.get("lng")

        existing_image = request.form["existing_image"]
        image_file = request.files["image"]

        filename = existing_image

        if image_file and image_file.filename != "":
            filename = image_file.filename
            image_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            image_file.save(image_path)

        conn.execute(
            """
            UPDATE observations
            SET date=?, location=?, species=?, count=?, bait=?, size=?, water=?, platform=?, comments=?, image=?, lat=?, lng=?
            WHERE id=?
            """,
            (date, location, species, count, bait, size, water, platform, comments, filename, lat, lng, id),
        )
        conn.commit()
        conn.close()

        return redirect("/")

    conn.close()
    return render_template("edit.html", record=record)


# -----------------------------
# DELETE ENTRY
# -----------------------------
@app.route("/delete/<int:id>", methods=["GET", "POST"])
@login_required
@role_required("write")
def delete(id):
    conn = get_db_connection()
    record = conn.execute("SELECT * FROM observations WHERE id = ?", (id,)).fetchone()

    if request.method == "POST":
        conn.execute("DELETE FROM observations WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        return redirect("/")

    conn.close()
    return render_template("delete.html", record=record)


# -----------------------------
# RUN SERVER
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

