import os
import sqlite3
from flask import Flask, render_template, request, redirect

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "static/uploads"

# Ensure upload folder exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


# -----------------------------
# DATABASE CONNECTION
# -----------------------------
def get_db_connection():
    conn = sqlite3.connect("mydatabase.db")
    conn.row_factory = sqlite3.Row
    return conn


# -----------------------------
# HOME PAGE (FILTER + SORT + SPECIES + MAP DATA + QUICK STATS)
# -----------------------------
@app.route("/")
def index():
    start = request.args.get("start")
    end = request.args.get("end")
    sort = request.args.get("sort", "newest")
    species_filter = request.args.get("species")

    query = "SELECT * FROM observations WHERE 1=1"
    params = []

    # Date filtering
    if start:
        query += " AND DATE(date) >= DATE(?)"
        params.append(start)

    if end:
        query += " AND DATE(date) <= DATE(?)"
        params.append(end)

    # Species filtering
    if species_filter and species_filter != "all":
        query += " AND species = ?"
        params.append(species_filter)

    # Sorting
    if sort == "oldest":
        query += " ORDER BY DATE(date) ASC"
    else:
        query += " ORDER BY DATE(date) DESC"

    conn = get_db_connection()

    # Species list for dropdown
    species_raw = conn.execute(
        "SELECT DISTINCT species FROM observations ORDER BY species ASC"
    ).fetchall()
    species_list = [dict(s) for s in species_raw]

    # Main data
    rows_raw = conn.execute(query, params).fetchall()
    rows = [dict(r) for r in rows_raw]

    # -----------------------------
    # QUICK STATS
    # -----------------------------
    total_trips = len(rows)

    total_fish = 0
    species_counts = {}

    for r in rows:
        # Count fish safely
        try:
            total_fish += int(r["count"]) if r["count"] else 0
        except:
            pass

        # Count species frequency
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
# REPORT PAGE (ADVANCED FILTERING)
# -----------------------------
@app.route("/report", methods=["GET"])
def report():
    start = request.args.get("start")
    end = request.args.get("end")
    species = request.args.get("species")
    location = request.args.get("location")
    water = request.args.get("water")
    platform = request.args.get("platform")

    query = "SELECT * FROM observations WHERE 1=1"
    params = []

    # Date filters
    if start:
        query += " AND DATE(date) >= DATE(?)"
        params.append(start)

    if end:
        query += " AND DATE(date) <= DATE(?)"
        params.append(end)

    # Species filter
    if species and species.strip() != "":
        query += " AND species LIKE ?"
        params.append(f"%{species}%")

    # Location filter
    if location and location.strip() != "":
        query += " AND location LIKE ?"
        params.append(f"%{location}%")

    # Water filter
    if water and water.strip() != "":
        query += " AND water LIKE ?"
        params.append(f"%{water}%")

    # Platform filter
    if platform and platform.strip() != "":
        query += " AND platform LIKE ?"
        params.append(f"%{platform}%")

    conn = get_db_connection()
    rows_raw = conn.execute(query, params).fetchall()
    rows = [dict(r) for r in rows_raw]
    conn.close()

    return render_template("report.html", rows=rows)


# -----------------------------
# ADD NEW ENTRY
# -----------------------------
@app.route("/add", methods=["GET", "POST"])
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
# EDIT ENTRY
# -----------------------------
@app.route("/edit/<int:id>", methods=["GET", "POST"])
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
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )

