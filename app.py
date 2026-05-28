import logging
import os
import sqlite3
import psycopg2
import psycopg2.extras
import datetime
from flask import Flask, render_template, request, redirect, abort

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
    UserMixin
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from dotenv import load_dotenv
load_dotenv()


app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "static/uploads"
app.config["SECRET_KEY"] = "super-secret-key"

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# -------------------------------------------------
# UNIVERSAL DB CONNECTION (SQLite locally, Postgres on Render)
# -------------------------------------------------
def get_db():
    postgres_url = os.getenv("POSTGRES_URL")

    if not postgres_url:
        logger.error("POSTGRES_URL is not set")
        raise RuntimeError("POSTGRES_URL is not set. Add it to your .env file.")

    logger.info("Connecting to Postgres")
    return psycopg2.connect(
        postgres_url,
        cursor_factory=psycopg2.extras.RealDictCursor
    )


# -----------------------------
# USER + AUTH SETUP
# -----------------------------
def get_user_connection():
    return get_db()

class User(UserMixin):
    def __init__(self, id, username, password_hash, role, last_login=None):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.role = role
        self.last_login = last_login

    @staticmethod
    def get(user_id):
        conn = get_user_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return User(row["id"], row["username"], row["password_hash"], row["role"], row["last_login"])
        return None

    @staticmethod
    def find_by_username(username):
        conn = get_user_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        conn.close()
        if row:
            return User(row["id"], row["username"], row["password_hash"], row["role"], row["last_login"])
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
    return get_db()

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
            conn = get_user_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET last_login = NOW() WHERE id = %s",
                (user.id,)
            )
            conn.commit()
            conn.close()

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
# USER LIST (ADMIN ONLY)
# -----------------------------
@app.route("/users")
@login_required
def users():
    if current_user.role != "admin":
        return "Access denied", 403

    conn = get_user_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, last_login FROM users")
    rows = cur.fetchall()
    conn.close()

    return render_template("users.html", users=rows)

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
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
            (username, hashed_pw, role)
        )
        conn.commit()
        conn.close()

        return redirect("/users")

    return render_template("create_user.html")

# -----------------------------
# SHOW TACKLE DASHBOARD
# -----------------------------
@app.route("/tackle")
@login_required
@role_required("read")
def tackle_dashboard():
    brand_filter = request.args.get("brand", "all")

    conn = get_db_connection()
    cur = conn.cursor()

    # Rods
    if brand_filter != "all":
        cur.execute("SELECT * FROM rods WHERE brand = %s ORDER BY brand", (brand_filter,))
    else:
        cur.execute("SELECT * FROM rods ORDER BY brand")
    rods = cur.fetchall()

    # Reels for display (filtered)
    if brand_filter != "all":
        cur.execute("SELECT * FROM reels WHERE brand = %s ORDER BY brand", (brand_filter,))
    else:
        cur.execute("SELECT * FROM reels ORDER BY brand")
    reels = cur.fetchall()

    # All reels for assignment dropdown
    cur.execute("SELECT * FROM reels ORDER BY brand, model")
    all_reels = cur.fetchall()

    # Line
    if brand_filter != "all":
        cur.execute("SELECT * FROM line WHERE brand = %s ORDER BY brand", (brand_filter,))
    else:
        cur.execute("SELECT * FROM line ORDER BY brand")
    line = cur.fetchall()

    conn.close()

    return render_template("tackle.html", rods=rods, reels=reels, all_reels=all_reels, line=line, brand_filter=brand_filter)


# -----------------------------
# ADD ROD ROUTE
# -----------------------------
@app.route("/add_rod", methods=["GET", "POST"])
@login_required
@role_required("write")
def add_rod():
    if request.method == "POST":
        brand = request.form["brand"]
        model = request.form["model"]
        series = request.form.get("series")
        length_ft = request.form.get("length_ft")
        action = request.form.get("action")
        cost = request.form.get("cost")
        source = request.form.get("source")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO rods (brand, model, series, length_ft, action, cost, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (brand, model, series, length_ft, action, cost, source))
        conn.commit()
        conn.close()

        return redirect("/tackle")

    return render_template("add_rod.html")

# -----------------------------
# ADD REEL ROUTE
# -----------------------------
@app.route("/add_reel", methods=["GET", "POST"])
@login_required
@role_required("write")
def add_reel():
    if request.method == "POST":
        brand = request.form["brand"]
        model = request.form["model"]
        cost = request.form.get("cost")
        source = request.form.get("source")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO reels (brand, model, cost, source)
            VALUES (%s, %s, %s, %s)
        """, (brand, model, cost, source))
        conn.commit()
        conn.close()

        return redirect("/tackle")

    return render_template("add_reel.html")


# -----------------------------
# ADD LINE ROUTE
# -----------------------------
@app.route("/add_line", methods=["GET", "POST"])
@login_required
@role_required("write")
def add_line():
    if request.method == "POST":
        brand = request.form["brand"]
        model = request.form["model"]
        type_ = request.form.get("type")
        strength = request.form.get("strength")
        cost = request.form.get("cost")
        source = request.form.get("source")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO line (brand, model, type, strength_lb, cost, source)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (brand, model, type_, strength, cost, source))
        conn.commit()
        conn.close()

        return redirect("/tackle")

    return render_template("add_line.html")


# -----------------------------
# ROD EDIT ROUTE
# -----------------------------
@app.route("/edit_rod/<int:id>", methods=["GET", "POST"])
@login_required
@role_required("write")
def edit_rod(id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM rods WHERE id = %s", (id,))
    rod = cur.fetchone()

    if not rod:
        conn.close()
        return "Rod not found", 404

    if request.method == "POST":
        brand = request.form["brand"]
        model = request.form["model"]
        series = request.form.get("series")
        length_ft = request.form.get("length_ft")
        action = request.form.get("action")
        cost = request.form.get("cost")
        source = request.form.get("source")

        cur.execute("""
            UPDATE rods
            SET brand=%s, model=%s, series=%s, length_ft=%s, action=%s, cost=%s, source=%s
            WHERE id=%s
        """, (brand, model, series, length_ft, action, cost, source, id))

        conn.commit()
        conn.close()
        return redirect("/tackle")

    conn.close()
    return render_template("edit_rod.html", rod=rod)


# -----------------------------
# ROD DELETE ROUTE
# -----------------------------
@app.route("/delete_rod/<int:id>", methods=["GET", "POST"])
@login_required
@role_required("write")
def delete_rod(id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM rods WHERE id = %s", (id,))
    rod = cur.fetchone()

    if not rod:
        conn.close()
        return "Rod not found", 404

    if request.method == "POST":
        cur.execute("DELETE FROM rods WHERE id = %s", (id,))
        conn.commit()
        conn.close()
        return redirect("/tackle")

    conn.close()
    return render_template("delete_rod.html", rod=rod)

# -----------------------------
# REEL EDIT ROUTE
# -----------------------------
@app.route("/edit_reel/<int:id>", methods=["GET", "POST"])
@login_required
@role_required("write")
def edit_reel(id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM reels WHERE id = %s", (id,))
    reel = cur.fetchone()

    if not reel:
        conn.close()
        return "Reel not found", 404

    if request.method == "POST":
        brand = request.form["brand"]
        model = request.form["model"]
        cost = request.form.get("cost")
        source = request.form.get("source")

        cur.execute("""
            UPDATE reels
            SET brand=%s, model=%s, cost=%s, source=%s
            WHERE id=%s
        """, (brand, model, cost, source, id))

        conn.commit()
        conn.close()
        return redirect("/tackle")

    conn.close()
    return render_template("edit_reel.html", reel=reel)


# -----------------------------
# REEL DELETE ROUTE
# -----------------------------
@app.route("/delete_reel/<int:id>", methods=["GET", "POST"])
@login_required
@role_required("write")
def delete_reel(id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM reels WHERE id = %s", (id,))
    reel = cur.fetchone()

    if not reel:
        conn.close()
        return "Reel not found", 404

    if request.method == "POST":
        cur.execute("DELETE FROM reels WHERE id = %s", (id,))
        conn.commit()
        conn.close()
        return redirect("/tackle")

    conn.close()
    return render_template("delete_reel.html", reel=reel)

# -----------------------------
# EDIT LINE ROUTE
# -----------------------------
@app.route("/edit_line/<int:id>", methods=["GET", "POST"])
@login_required
@role_required("write")
def edit_line(id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM line WHERE id = %s", (id,))
    l = cur.fetchone()

    if not l:
        conn.close()
        return "Line not found", 404

    if request.method == "POST":
        brand = request.form["brand"]
        model = request.form["model"]
        type_ = request.form.get("type")
        strength = request.form.get("strength_lb")
        cost = request.form.get("cost")
        source = request.form.get("source")

        cur.execute("""
            UPDATE line
            SET brand=%s, model=%s, type=%s, strength_lb=%s, cost=%s, source=%s
            WHERE id=%s
        """, (brand, model, type_, strength, cost, source, id))

        conn.commit()
        conn.close()
        return redirect("/tackle")

    conn.close()
    return render_template("edit_line.html", l=l)



# -----------------------------
# DELETE LINE ROUTE
# -----------------------------
@app.route("/delete_line/<int:id>", methods=["GET", "POST"])
@login_required
@role_required("write")
def delete_line(id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM line WHERE id = %s", (id,))
    l = cur.fetchone()

    if not l:
        conn.close()
        return "Line not found", 404

    if request.method == "POST":
        cur.execute("DELETE FROM line WHERE id = %s", (id,))
        conn.commit()
        conn.close()
        return redirect("/tackle")

    conn.close()
    return render_template("delete_line.html", l=l)

# -----------------------------
# UPDATE ROD → REEL LINK
# -----------------------------
@app.route("/update_rod_reel", methods=["POST"])
@login_required
@role_required("write")
def update_rod_reel():
    rod_id = request.form["rod_id"]
    reel_id = request.form.get("reel_id") or None

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "UPDATE rods SET reel_id = %s WHERE id = %s",
        (reel_id, rod_id)
    )

    conn.commit()
    conn.close()

    return redirect("/tackle")


# -----------------------------
# CHANGE USER ROLE (ADMIN ONLY)
# -----------------------------
@app.route("/change_role/<int:id>", methods=["GET", "POST"])
@login_required
def change_role(id):
    if current_user.role != "admin":
        return "Access denied", 403

    conn = get_user_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role FROM users WHERE id = %s", (id,))
    user = cur.fetchone()

    if not user:
        conn.close()
        return "User not found", 404

    if request.method == "POST":
        new_role = request.form["role"]
        cur.execute(
            "UPDATE users SET role = %s WHERE id = %s",
            (new_role, id)
        )
        conn.commit()
        conn.close()
        return redirect("/users")

    conn.close()
    return render_template("edit_user_role.html", user=user)

# -----------------------------
# CHANGE PASSWORD
# -----------------------------
@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old_password = request.form["old_password"]
        new_password = request.form["new_password"]

        if not current_user.check_password(old_password):
            return "Old password is incorrect", 400

        new_hash = generate_password_hash(new_password)

        conn = get_user_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (new_hash, current_user.id)
        )
        conn.commit()
        conn.close()

        return redirect("/")

    return render_template("change_password.html")

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
        query += " AND date >= %s"
        params.append(start)

    if end:
        query += " AND date <= %s"
        params.append(end)

    if species_filter and species_filter != "all":
        query += " AND species = %s"
        params.append(species_filter)

    if sort == "oldest":
        query += " ORDER BY date ASC"
    else:
        query += " ORDER BY date DESC"

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT species FROM observations ORDER BY species ASC")
    species_list = cur.fetchall()

    cur.execute(query, params)
    rows = cur.fetchall()

    total_trips = len(rows)
    total_fish = sum(int(r["count"] or 0) for r in rows)

    logger.info("index called: total_trips=%s total_fish=%s", total_trips, total_fish)

    species_counts = {}

    for r in rows:
        sp = r["species"]
        if sp:
            species_counts[sp] = species_counts.get(sp, 0) + 1

    most_common_species = max(species_counts, key=species_counts.get) if species_counts else None

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
# TRIP SUMMARY PAGE
# -----------------------------
@app.route("/trip")
@login_required
@role_required("read")
def trip_summary():
    date = request.args.get("date")
    location = request.args.get("location")

    if not date or not location:
        return "Missing trip parameters", 400

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT * FROM observations
        WHERE date = %s AND location = %s
        ORDER BY species ASC
        """,
        (date, location)
    )
    rows = cur.fetchall()

    total_fish = sum(int(r["count"]) if r["count"] and str(r["count"]).strip() else 0 for r in rows)
    species_set = {r["species"] for r in rows if r["species"]}
    unique_species = len(species_set)

    species_counts = {}
    for r in rows:
        sp = r["species"]
        if sp:
            species_counts[sp] = species_counts.get(sp, 0) + (int(r["count"]) if r["count"] and str(r["count"]).strip() else 0)

    trip_lat = None
    trip_lng = None

    for r in rows:
        lat = r.get("lat")
        lng = r.get("lng")
        if lat and lng:
            try:
                trip_lat = float(lat)
                trip_lng = float(lng)
                break
            except:
                pass

    youtube_url = rows[0].get("youtube_url") if rows else None

    conn.close()

    return render_template(
        "trip_summary.html",
        date=date,
        location=location,
        data=rows,
        total_fish=total_fish,
        unique_species=unique_species,
        species_counts=species_counts,
        trip_lat=trip_lat,
        trip_lng=trip_lng,
        youtube_url=youtube_url
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
    species_filter = request.args.get("species")

    query = "SELECT * FROM observations WHERE 1=1"
    params = []

    if start:
        query += " AND date >= %s"
        params.append(start)

    if end:
        query += " AND date <= %s"
        params.append(end)

    if species_filter and species_filter != "all":
        query += " AND species = %s"
        params.append(species_filter)

    query += " ORDER BY date DESC"

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT species FROM observations ORDER BY species ASC")
    species_list = cur.fetchall()

    cur.execute(query, params)
    rows = cur.fetchall()

    total_trips = len(rows)
    total_fish = sum(int(r["count"]) if r["count"] and str(r["count"]).strip() else 0 for r in rows)
    unique_species = len({r["species"] for r in rows if r["species"]})

    conn.close()

    return render_template(
        "report.html",
        data=rows,
        species_list=species_list,
        total_trips=total_trips,
        total_fish=total_fish,
        unique_species=unique_species
    )

# -----------------------------
# HISTORY PAGE
# -----------------------------
from psycopg2.extras import DictCursor

@app.route("/history")
@login_required
@role_required("read")
def history():
    year_filter = request.args.get("year")
    species_filter = request.args.get("species")
    water_filter = request.args.get("water")
    sort_order = request.args.get("sort", "desc")

    query = "SELECT * FROM historical_catches WHERE 1=1"
    params = []

    if year_filter:
        query += " AND EXTRACT(YEAR FROM catch_date) = %s"
        params.append(year_filter)

    if species_filter:
        query += " AND species = %s"
        params.append(species_filter)

    if water_filter:
        query += " AND water_type = %s"
        params.append(water_filter)

    if sort_order == "asc":
        query += " ORDER BY catch_date ASC"
    else:
        query += " ORDER BY catch_date DESC"

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)

    # Dropdowns
    cur.execute("""
        SELECT DISTINCT EXTRACT(YEAR FROM catch_date) AS year
        FROM historical_catches
        ORDER BY year DESC
    """)
    years = [int(r["year"]) for r in cur.fetchall()]

    cur.execute("""
        SELECT DISTINCT species
        FROM historical_catches
        WHERE species IS NOT NULL AND species != ''
        ORDER BY species ASC
    """)
    species_list = [r["species"] for r in cur.fetchall()]

    cur.execute("""
        SELECT DISTINCT water_type
        FROM historical_catches
        WHERE water_type IS NOT NULL AND water_type != ''
        ORDER BY water_type ASC
    """)
    water_types = [r["water_type"] for r in cur.fetchall()]

    # Main query
    cur.execute(query, params)
    catches = cur.fetchall()

    total_catches = len(catches)
    total_fish = sum(int(c.get("quantity") or 0) for c in catches)

    logger.info("history called: year=%s species=%s water=%s sort=%s total_catches=%s total_fish=%s", year_filter, species_filter, water_filter, sort_order, total_catches, total_fish)

    conn.close()

    return render_template(
        "history.html",
        catches=catches,
        years=years,
        species_list=species_list,
        water_types=water_types,
        selected_year=year_filter,
        selected_species=species_filter,
        selected_water=water_filter,
        sort_order=sort_order,
        total_catches=total_catches,
        total_fish=total_fish
    )

# -----------------------------
# ADD ENTRY
# -----------------------------
@app.route("/add", methods=["GET", "POST"])
@login_required
@role_required("write")
def add():
    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch all trips for the dropdown (GET and POST both need this)
    cur.execute("SELECT id, date, location FROM trips ORDER BY date DESC")
    trips = cur.fetchall()

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

        water_temp = request.form.get("water_temp")
        wind = request.form.get("wind")
        wave_height = request.form.get("wave_height")

        lat = request.form.get("lat")
        lng = request.form.get("lng")
        angler = request.form["angler"]

        youtube_url = request.form.get("youtube_url")

        # NEW: Trip ID from dropdown
        trip_id = request.form.get("trip_id") or None

        # Handle image upload
        image_file = request.files.get("image")
        filename = None

        if image_file and image_file.filename != "":
            filename = secure_filename(image_file.filename)
            image_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            image_file.save(image_path)

        # Insert catch including trip_id
        cur.execute(
            """
            INSERT INTO observations 
            (date, location, species, count, bait, size, water, platform, comments,
             image, lat, lng, water_temp, wind, wave_height, angler, youtube_url, trip_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                date, location, species, count, bait, size, water, platform, comments,
                filename, lat, lng, water_temp, wind, wave_height, angler, youtube_url, trip_id
            ),
        )

        conn.commit()
        conn.close()

        return redirect("/")

    conn.close()
    return render_template("add.html", trips=trips)
# -----------------------------
# EDIT ENTRY
# -----------------------------
@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch the observation being edited
    cur.execute("SELECT * FROM observations WHERE id = %s", (id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return "Entry not found", 404

    # -----------------------------
    # POST: Save changes
    # -----------------------------
    if request.method == "POST":
        date = request.form["date"]
        location = request.form["location"]
        species = request.form["species"]
        count = request.form["count"]
        bait = request.form["bait"]
        size = request.form["size"]
        water = request.form["water"]
        platform = request.form["platform"]
        water_temp = request.form["water_temp"]
        wind = request.form["wind"]
        wave_height = request.form["wave_height"]
        comments = request.form["comments"]
        lat = request.form["lat"]
        lng = request.form["lng"]
        angler = request.form.get("angler")
        youtube_url = request.form.get("youtube_url")

        # Trip selection (may be empty string)
        trip_id = request.form.get("trip_id")

        # ⭐ Option 1 fix: convert empty string to None
        if trip_id == "":
            trip_id = None

        # Handle image upload
        image = row["image"]
        file = request.files.get("image")
        if file and file.filename != "":
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            image = filename


        # Update DB
        cur.execute(
            """
            UPDATE observations
            SET date=%s, location=%s, species=%s, count=%s, bait=%s, size=%s, water=%s, platform=%s,
                water_temp=%s, wind=%s, wave_height=%s, comments=%s, image=%s, lat=%s, lng=%s,
                angler=%s, youtube_url=%s, trip_id=%s
            WHERE id=%s
            """,
            (
                date, location, species, count, bait, size, water, platform,
                water_temp, wind, wave_height, comments, image, lat, lng,
                angler, youtube_url, trip_id, id
            )
        )

        conn.commit()
        conn.close()
        return redirect("/")

    # -----------------------------
    # GET: Load edit form
    # -----------------------------

    # NEW: Load all trips for dropdown
    cur.execute("SELECT id, date, location FROM trips ORDER BY date DESC")
    trips = cur.fetchall()

    conn.close()
    return render_template("edit.html", row=row, trips=trips)



# -----------------------------
# ADD TRIP
# ----------------------------

@app.route("/trip/add", methods=["GET", "POST"])
def add_trip():
    if request.method == "POST":
        date = request.form["date"]
        location = request.form["location"]
        notes = request.form.get("notes")
        angler = request.form.get("angler")

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "INSERT INTO trips (date, location, notes, angler) VALUES (%s, %s, %s, %s)",
            (date, location, notes, angler)
        )

        conn.commit()
        conn.close()

        return redirect("/trips")

    return render_template("add_trip.html")


# -----------------------------
# ADD TRIPS
# ----------------------------

@app.route("/trips")
@login_required
@role_required("read")
def trips():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, date, location, notes, angler FROM trips ORDER BY date DESC")
    trips = cur.fetchall()

    conn.close()

    return render_template("trips.html", trips=trips)



# -----------------------------
# EDIT TRIPS
# ----------------------------

@app.route("/trip/edit/<int:id>", methods=["GET", "POST"])
@login_required
@role_required("write")
def edit_trip(id):
    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch existing trip
    cur.execute("SELECT * FROM trips WHERE id = %s", (id,))
    trip = cur.fetchone()

    if not trip:
        conn.close()
        return "Trip not found", 404

    if request.method == "POST":
        date = request.form["date"]
        location = request.form["location"]
        angler = request.form.get("angler")
        notes = request.form.get("notes")

        cur.execute("""
            UPDATE trips
            SET date = %s, location = %s, angler = %s, notes = %s
            WHERE id = %s
        """, (date, location, angler, notes, id))

        conn.commit()
        conn.close()
        return redirect("/trips")

    conn.close()
    return render_template("edit_trip.html", trip=trip)



# -----------------------------
# DELETE TRIPS
# ----------------------------

@app.route("/trip/delete/<int:id>", methods=["GET", "POST"])
@login_required
@role_required("write")
def delete_trip(id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM trips WHERE id = %s", (id,))
    trip = cur.fetchone()

    if not trip:
        conn.close()
        return "Trip not found", 404

    if request.method == "POST":
        cur.execute("DELETE FROM trips WHERE id = %s", (id,))
        conn.commit()
        conn.close()
        return redirect("/trips")

    conn.close()
    return render_template("delete_trip.html", trip=trip)



# -----------------------------
# HEATMAP
# -----------------------------
@app.route("/heatmap")
@login_required
@role_required("read")
def heatmap():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT species, date, count
        FROM observations
        WHERE species IS NOT NULL AND species != ''
    """)
    rows = cur.fetchall()

    conn.close()

    heatmap_data = {}
    for r in rows:
        species = r["species"]
        date_value = r.get("date")
        if not date_value:
            continue

        month = None
        if isinstance(date_value, (datetime.date, datetime.datetime)):
            month = date_value.month
        else:
            try:
                month = datetime.datetime.strptime(str(date_value), "%Y-%m-%d").month
            except ValueError:
                try:
                    month = datetime.datetime.strptime(str(date_value), "%Y-%m-%d %H:%M:%S").month
                except ValueError:
                    continue

        count = int(r.get("count") or 0)
        if species not in heatmap_data:
            heatmap_data[species] = {m: 0 for m in range(1, 13)}

        heatmap_data[species][month] += count

    return render_template("heatmap.html", heatmap_data=heatmap_data)



# -----------------------------
# DELETE ENTRY
# -----------------------------
@app.route("/delete/<int:id>", methods=["GET", "POST"])
@login_required
@role_required("write")
def delete(id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM observations WHERE id = %s", (id,))
    record = cur.fetchone()

    if not record:
        conn.close()
        return "Entry not found", 404

    if request.method == "POST":
        cur.execute("DELETE FROM observations WHERE id = %s", (id,))
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
