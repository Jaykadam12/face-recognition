# ===== refactored app.py =====
# Place this file as app.py

import os
import io
import threading
import sqlite3
import json
import random
from datetime import datetime, timedelta, timezone, date
from threading import Lock
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for,flash,session
from functools import wraps



APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "attendance.db")
DATASET_DIR = os.path.join(APP_DIR, "dataset")
os.makedirs(DATASET_DIR, exist_ok=True)

TRAIN_STATUS_FILE = os.path.join(APP_DIR, "train_status.json")
train_status_lock = Lock()

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = "12345"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# ---------- DB helpers ----------
def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Please login as admin first.", "danger")
            return redirect(url_for("admin_login"))
        return func(*args, **kwargs)
    return wrapper

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            flash("Admin login successful!", "success")
            return redirect(url_for("admin_dashboard"))

        flash("Invalid username or password!", "danger")
        return redirect(url_for("admin_login"))

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    flash("Logged out successfully.", "success")
    return redirect(url_for("index"))

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    return render_template("admin_dashboard.html")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Students table
    c.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            roll TEXT,
            class TEXT,
            section TEXT,
            reg_no TEXT,
            created_at TEXT
        )
    """)

    # Attendance table
    c.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            name TEXT,
            class TEXT,
            section TEXT,
            subject TEXT,
            teacher TEXT,
            start_time TEXT,
            end_time TEXT,
            timestamp TEXT
        )
    """)

    # Timetable table (UPDATED)
    c.execute("""
        CREATE TABLE IF NOT EXISTS timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class TEXT NOT NULL,
            section TEXT NOT NULL,
            day TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            subject TEXT NOT NULL,
            teacher TEXT NOT NULL
        )
    """)

    # Unique slot per class + section + time
    c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uniq_timetable_slot
        ON timetable(class, section, day, start_time, end_time)
    """)

    conn.commit()
    conn.close()

def add_missing_columns():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # try add subject column
    try:
        c.execute("ALTER TABLE attendance ADD COLUMN subject TEXT")
    except:
        pass

    # try add teacher column
    try:
        c.execute("ALTER TABLE attendance ADD COLUMN teacher TEXT")
    except:
        pass

    try:
        c.execute("ALTER TABLE attendance ADD COLUMN start_time TEXT")
    except:
        pass

    # ✅ NEW
    try:
        c.execute("ALTER TABLE attendance ADD COLUMN end_time TEXT")
    except:
        pass

    conn.commit()
    conn.close()

def get_current_timetable_slot(student_class, student_section):
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)

    day = now.strftime("%A")
    current_time = now.strftime("%H:%M")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT subject, teacher, start_time, end_time
        FROM timetable
        WHERE class=? AND section=? AND day=?
        AND start_time <= ?
        AND end_time > ?
        LIMIT 1
    """, (student_class, student_section, day, current_time, current_time))

    row = c.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "subject": row[0],
        "teacher": row[1],
        "start_time": row[2],
        "end_time": row[3]
    }


@app.route("/clear_attendance", methods=["POST"])
@admin_required
def clear_attendance():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM attendance")
    conn.commit()
    conn.close()
    return jsonify({"cleared": True})


init_db()
add_missing_columns()

@app.route("/debug_slot")
@admin_required
def debug_slot():

    # get class + section from URL
    student_class = request.args.get("class", "TE")
    student_section = request.args.get("section", "A")

    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)

    day = now.strftime("%A")
    current_time = now.strftime("%H:%M")

    slot = get_current_timetable_slot(student_class, student_section)

    return jsonify({
        "class": student_class,
        "section": student_section,
        "day": day,
        "current_time": current_time,
        "slot_found": slot
    })

def write_train_status(status_dict):
    with train_status_lock:
        with open(TRAIN_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status_dict, f)


def read_train_status():
    if not os.path.exists(TRAIN_STATUS_FILE):
        return {"running": False, "progress": 0, "message": "No training started yet"}
    try:
        with train_status_lock:
            with open(TRAIN_STATUS_FILE, "r", encoding="utf-8") as f:
                data = f.read().strip()
                if not data:
                    return {"running": False, "progress": 0, "message": "Training not started or empty status"}
                return json.loads(data)
    except Exception as e:
        return {"running": False, "progress": 0, "message": f"Error reading status: {e}"}


# ensure initial train status file exists
write_train_status({"running": False, "progress": 0, "message": "No training yet."})

# ---------- Routes ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/timetable", methods=["GET", "POST"])
@admin_required
def timetable_page():

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    selected_class = request.args.get("class", "TE")
    selected_section = request.args.get("section", "A")
    selected_day = request.args.get("day", "Monday")

    # ---------- ADD SLOT ----------
    if request.method == "POST":

        selected_class = request.form.get("class")
        selected_section = request.form.get("section")
        selected_day = request.form.get("day")

        start_time = request.form.get("start_time")
        end_time = request.form.get("end_time")
        subject = request.form.get("subject")
        teacher = request.form.get("teacher")

        try:
            c.execute("""
                INSERT INTO timetable
                (class, section, day, start_time, end_time, subject, teacher)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                selected_class,
                selected_section,
                selected_day,
                start_time,
                end_time,
                subject,
                teacher
            ))

            conn.commit()
            flash("Slot added successfully!", "success")

        except Exception:
            flash("Slot already exists!", "danger")

        conn.close()

        return redirect(url_for(
            "timetable_page",
            **{
                "class": selected_class,
                "section": selected_section,
                "day": selected_day
            }
        ))

    # ---------- FETCH ----------
    c.execute("""
        SELECT *
        FROM timetable
        WHERE class=? AND section=? AND day=?
        ORDER BY start_time ASC
    """, (selected_class, selected_section, selected_day))

    rows = c.fetchall()
    conn.close()

    return render_template(
        "timetable.html",
        rows=rows,
        selected_class=selected_class,
        selected_section=selected_section,
        selected_day=selected_day
    )


@app.route("/add_dummy_attendance")
@admin_required
def add_dummy_attendance():
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)

    # take current timetable slot
    slot = get_current_timetable_slot()
    if not slot:
        return jsonify({"ok": False, "error": "No active timetable slot right now"}), 400

    subject = slot["subject"]
    teacher = slot["teacher"]
    start_time = slot.get("start_time")
    end_time = slot.get("end_time")

    ts = now.strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # pick first student
    c.execute("SELECT roll, name FROM students ORDER BY id ASC LIMIT 1")
    s = c.fetchone()
    if not s:
        conn.close()
        return jsonify({"ok": False, "error": "No students found"}), 400

    roll, name = str(s[0]), s[1]

    # insert attendance (no duplicate check for testing)
    c.execute("""
        INSERT INTO attendance (student_id, name, subject, teacher, start_time, end_time, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (roll, name, subject, teacher, start_time, end_time, ts))

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "message": "Dummy attendance inserted",
        "student_id": roll,
        "name": name,
        "subject": subject,
        "timestamp": ts
    })


@app.route("/timetable/delete/<int:tid>", methods=["POST"])
@admin_required
def delete_timetable(tid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM timetable WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    return jsonify({"deleted": True})


@app.route("/timetable/edit/<int:tid>", methods=["POST"])
@admin_required
def edit_timetable(tid):
    day = request.form.get("day")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    subject = request.form.get("subject")
    teacher = request.form.get("teacher")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # prevent same slot duplication
    c.execute("""
        SELECT id FROM timetable
        WHERE day=? AND start_time=? AND end_time=? AND id != ?
    """, (day, start_time, end_time, tid))
    exists = c.fetchone()

    if exists:
        conn.close()
        return jsonify({"updated": False, "error": "Slot already exists for that day/time"}), 400

    c.execute("""
        UPDATE timetable
        SET day=?, start_time=?, end_time=?, subject=?, teacher=?
        WHERE id=?
    """, (day, start_time, end_time, subject, teacher, tid))

    conn.commit()
    conn.close()

    return jsonify({"updated": True})


# Dashboard simple API for attendance stats (last 30 days)
@app.route("/attendance_stats")
@admin_required
def attendance_stats():
    import pandas as pd
    import pytz

    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT timestamp FROM attendance", conn)
    conn.close()

    if df.empty:
        days = [(date.today() - timedelta(days=i)).strftime("%d-%b") for i in range(29, -1, -1)]
        return jsonify({"dates": days, "counts": [0] * 30})

    # Convert timestamp to datetime (assume ISO-like strings stored)
    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
    df['date'] = df['timestamp'].dt.date

    last_30 = [(date.today() - timedelta(days=i)) for i in range(29, -1, -1)]
    counts = [int(df[df['date'] == d].shape[0]) for d in last_30]
    dates = [d.strftime("%d-%b") for d in last_30]

    return jsonify({"dates": dates, "counts": counts})


# -------- Add student (form) --------
@app.route("/add_student", methods=["GET", "POST"])
def add_student():
    if request.method == "GET":
        return render_template("add_student.html")

    data = request.form
    name = data.get("name", "").strip()
    roll = data.get("roll", "").strip()
    cls = data.get("class", "").strip()
    sec = data.get("sec", "").strip()
    reg_no = data.get("reg_no", "").strip()

    if not name or not roll:
        return jsonify({"error": "Name and roll number are required"}), 400

    # Indian time (IST)
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO students (name, roll, class, section, reg_no, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (name, roll, cls, sec, reg_no, now),
    )
    conn.commit()
    conn.close()

    # Create dataset folder using roll number
    student_folder = os.path.join(DATASET_DIR, str(roll))
    os.makedirs(student_folder, exist_ok=True)

    return jsonify({"student_id": roll})


# -------- Upload face images (after capture) --------
@app.route("/upload_face", methods=["POST"])
def upload_face():
    from model import save_student_encoding  # local import to avoid circular issues

    student_id = request.form.get("student_id")
    if not student_id:
        return jsonify({"error": "student_id required"}), 400

    name = request.form.get("name", "")  # optionally pass name in form; otherwise lookup DB
    # fallback: if no name provided, try DB lookup
    if not name:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name FROM students WHERE roll=?", (student_id,))
        row = c.fetchone()
        conn.close()
        if row:
            name = row[0]
        else:
            name = ""

    files = request.files.getlist("images[]")
    saved = 0

    # For each uploaded image, compute encoding and save to students.csv
    for f in files:
        try:
            ok = save_student_encoding(student_id, name, f.stream if hasattr(f, "stream") else f)
            if ok:
                saved += 1
        except Exception as e:
            app.logger.error("save encoding error: %s", e)

    # Do not auto-train classifier (we now use direct encodings). Return saved count
    return jsonify({"saved": saved})


# -------- Train progress (polling) --------
@app.route("/train_status", methods=["GET"])
def train_status():
    return jsonify(read_train_status())


# -------- Mark attendance page --------
@app.route("/mark_attendance", methods=["GET"])
def mark_attendance_page():
    return render_template("mark_attendance.html")


# -------- Recognize face endpoint (POST image) --------
@app.route("/recognize_face", methods=["POST"])
def recognize_face():
    from model import recognize_face_from_image

    if "image" not in request.files:
        return jsonify({"recognized": False, "error": "no image"}), 400

    img_file = request.files["image"]

    try:
        # Recognize face
        pred_roll, pred_name, _ = recognize_face_from_image(
            img_file.stream if hasattr(img_file, "stream") else img_file
        )

        if pred_roll is None:
            return jsonify({"recognized": False, "error": "no match"}), 200

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Fetch student info (IMPORTANT: get class & section)
        c.execute("""
            SELECT name, class, section 
            FROM students 
            WHERE roll=?
        """, (str(pred_roll),))

        row = c.fetchone()

        if not row:
            conn.close()
            return jsonify({"recognized": False, "error": "Student not found"}), 200

        name = pred_name if pred_name else row[0]
        student_class = row[1]
        student_section = row[2]

        # Get current IST time
        ist = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(ist)
        today_ist = now.date().isoformat()

        # Get timetable slot for this student's class
        slot = get_current_timetable_slot(student_class, student_section)

        if not slot:
            conn.close()
            return jsonify({
                "recognized": True,
                "student_id": str(pred_roll),
                "name": name,
                "attendance_marked": False,
                "error": "No class scheduled right now"
            }), 200

        subject = slot["subject"]
        teacher = slot["teacher"]
        start_time = slot["start_time"]
        end_time = slot["end_time"]

        # Duplicate check
        c.execute("""
            SELECT id FROM attendance
            WHERE student_id=?
            AND substr(timestamp,1,10)=?
            AND subject=?
            AND start_time=?
        """, (str(pred_roll), today_ist, subject, start_time))

        already_marked = c.fetchone()
        marked = False

        if not already_marked:
            ts = now.strftime("%Y-%m-%d %H:%M:%S")

            c.execute("""
                INSERT INTO attendance (
                    student_id,
                    name,
                    class,
                    section,
                    subject,
                    teacher,
                    start_time,
                    end_time,
                    timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(pred_roll),
                name,
                student_class,
                student_section,
                subject,
                teacher,
                start_time,
                end_time,
                ts
            ))

            conn.commit()
            marked = True

        conn.close()

        return jsonify({
            "recognized": True,
            "student_id": str(pred_roll),
            "name": name,
            "class": student_class,
            "section": student_section,
            "subject": subject,
            "teacher": teacher,
            "start_time": start_time,
            "end_time": end_time,
            "attendance_marked": marked
        }), 200

    except Exception as e:
        app.logger.exception("recognize error")
        return jsonify({"recognized": False, "error": str(e)}), 500
    

@app.route("/debug_students")
def debug_students():

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT * FROM students")
    rows = c.fetchall()

    conn.close()

    return jsonify(rows)

@app.route("/admin_attendance")
@admin_required
def admin_attendance():

    selected_class = request.args.get("class", "TE")
    selected_section = request.args.get("section", "A")
    selected_date = request.args.get("date")

    if not selected_date:
        selected_date = date.today().isoformat()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get students of class
    c.execute("""
        SELECT id, roll, name, class, section
        FROM students
        WHERE class=? AND section=?
        ORDER BY roll
    """, (selected_class, selected_section))

    students = c.fetchall()

    # Get attendance for date
    c.execute("""
        SELECT id, student_id
        FROM attendance
        WHERE substr(timestamp,1,10)=?
        AND class=? AND section=?
    """, (selected_date, selected_class, selected_section))

    attendance_rows = c.fetchall()
    attendance_map = {str(r[1]): r[0] for r in attendance_rows}

    records = []

    for sid, roll, name, cls, sec in students:

        if str(roll) in attendance_map:
            present = True
            aid = attendance_map[str(roll)]
        else:
            present = False
            aid = None

        records.append({
            "sid": sid,
            "roll": roll,
            "name": name,
            "class": cls,
            "section": sec,
            "present": present,
            "attendance_id": aid
        })

    conn.close()

    return render_template(
        "admin_attendance.html",
        records=records,
        selected_class=selected_class,
        selected_section=selected_section,
        selected_date=selected_date
    )

@app.route("/admin_mark_present", methods=["POST"])
@admin_required
def admin_mark_present():

    roll = request.form.get("roll")
    cls = request.form.get("class")
    sec = request.form.get("section")
    date_str = request.form.get("date")

    ts = f"{date_str} 09:00:00"

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT name FROM students
        WHERE roll=? AND class=? AND section=?
    """, (roll, cls, sec))

    row = c.fetchone()

    if row:
        name = row[0]

        c.execute("""
            INSERT INTO attendance
            (student_id, name, class, section, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (roll, name, cls, sec, ts))

        conn.commit()

    conn.close()

    return jsonify({"success": True})

@app.route("/admin_delete_attendance/<int:aid>", methods=["POST"])
@admin_required
def admin_delete_attendance(aid):

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("DELETE FROM attendance WHERE id=?", (aid,))
    conn.commit()
    conn.close()

    return jsonify({"success": True})

@app.route("/admin_update_student", methods=["POST"])
@admin_required
def admin_update_student():

    sid = request.form.get("sid")
    name = request.form.get("name")
    cls = request.form.get("class")
    sec = request.form.get("section")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        UPDATE students
        SET name=?, class=?, section=?
        WHERE id=?
    """, (name, cls, sec, sid))

    conn.commit()
    conn.close()

    return jsonify({"success": True})

@app.route("/admin_delete_student/<int:sid>", methods=["POST"])
@admin_required
def admin_delete_student(sid):

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT roll FROM students WHERE id=?", (sid,))
    row = c.fetchone()

    if row:
        roll = row[0]
        c.execute("DELETE FROM attendance WHERE student_id=?", (str(roll),))

    c.execute("DELETE FROM students WHERE id=?", (sid,))

    conn.commit()
    conn.close()

    return jsonify({"success": True})

# -------- Attendance records & filters --------
@app.route("/attendance_record", methods=["GET"])
def attendance_record():
    period = request.args.get("period", "all")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    q = "SELECT id, student_id, name, subject, teacher, start_time, end_time, timestamp FROM attendance"
    params = ()

    if period == "daily":
        today = date.today().isoformat()
        q += " WHERE substr(timestamp,1,10) = ?"
        params = (today,)
    elif period == "weekly":
        start = (date.today() - timedelta(days=7)).isoformat()
        q += " WHERE substr(timestamp,1,10) >= ?"
        params = (start,)
    elif period == "monthly":
        start = (date.today() - timedelta(days=30)).isoformat()
        q += " WHERE substr(timestamp,1,10) >= ?"
        params = (start,)

    q += " ORDER BY timestamp DESC LIMIT 5000"
    c.execute(q, params)
    rows = c.fetchall()
    conn.close()

    formatted_records = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(r[7])
            day_name = ts.strftime("%A")        # Tuesday
            time_str = ts.strftime("%I:%M %p")  # 07:44 PM
        except Exception:
            day_name = "N/A"
            time_str = r[7]

        # r = (id, roll, name, subject, teacher, start_time, end_time, timestamp)
        formatted_records.append((r[0], r[1], r[2], r[3], r[4], r[5], r[6], day_name, time_str))

    return render_template("attendance_record.html", records=formatted_records, period=period)

@app.route("/monthly_defaulters")
@admin_required
def monthly_defaulters():

    month = request.args.get("month")
    threshold = float(request.args.get("threshold", 75))

    selected_class = request.args.get("class", "TE")
    selected_section = request.args.get("section", "A")

    if not month:
        month = date.today().strftime("%Y-%m")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ---------- TOTAL SESSIONS (CLASS WISE) ----------
    c.execute("""
        SELECT COUNT(DISTINCT substr(timestamp,1,10) || '_' || subject || '_' || IFNULL(start_time,''))
        FROM attendance
        WHERE substr(timestamp,1,7)=?
        AND class=?
        AND section=?
        AND subject IS NOT NULL
    """, (month, selected_class, selected_section))

    total_sessions = c.fetchone()[0] or 0

    if total_sessions == 0:
        conn.close()
        return jsonify({
            "month": month,
            "class": selected_class,
            "section": selected_section,
            "total_sessions": 0,
            "defaulters": [],
            "message": "No sessions found for this class."
        })

    # ---------- ATTENDANCE COUNT ----------
    c.execute("""
        SELECT student_id, COUNT(*) as attended
        FROM attendance
        WHERE substr(timestamp,1,7)=?
        AND class=?
        AND section=?
        GROUP BY student_id
    """, (month, selected_class, selected_section))

    attendance_rows = c.fetchall()
    attended_map = {str(r[0]): int(r[1]) for r in attendance_rows}

    # ---------- STUDENTS OF THIS CLASS ----------
    c.execute("""
        SELECT roll, name
        FROM students
        WHERE class=? AND section=?
    """, (selected_class, selected_section))

    students = c.fetchall()

    conn.close()

    result = []

    for roll, name in students:

        attended = attended_map.get(str(roll), 0)
        percent = (attended / total_sessions) * 100

        if percent < threshold:

            result.append({
                "roll": str(roll),
                "name": name,
                "attended": attended,
                "total_sessions": total_sessions,
                "percentage": round(percent, 2)
            })

    return jsonify({
        "month": month,
        "class": selected_class,
        "section": selected_section,
        "total_sessions": total_sessions,
        "defaulters": result
    })

@app.route("/cleanup_timetable")
@admin_required
def cleanup_timetable():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Keep only the first row for each (day, start_time, end_time)
    c.execute("""
        DELETE FROM timetable
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM timetable
            GROUP BY day, start_time, end_time
        )
    """)

    conn.commit()
    conn.close()
    return "✅ Timetable duplicates removed successfully!"

import random

@app.route("/seed_dummy_data")
@admin_required
def seed_dummy_data():
    month = request.args.get("month")  # YYYY-MM
    sessions_count = int(request.args.get("sessions", 20))  # how many sessions
    present_percent = int(request.args.get("present", 70))  # % students present per session

    if not month:
        month = date.today().strftime("%Y-%m")

    year, mon = map(int, month.split("-"))
    ist = timezone(timedelta(hours=5, minutes=30))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get all students
    c.execute("SELECT roll, name FROM students")
    students = c.fetchall()

    if not students:
        conn.close()
        return jsonify({"ok": False, "error": "No students found"}), 400

    # Get timetable subjects (use for realistic sessions)
    c.execute("SELECT subject, teacher, start_time, end_time FROM timetable")
    slots = c.fetchall()

    if not slots:
        conn.close()
        return jsonify({"ok": False, "error": "No timetable slots found"}), 400

    # Create random sessions in the month
    created_sessions = 0
    created_attendance = 0

    for i in range(sessions_count):
        # random day in month (1-28 safe)
        day_num = random.randint(1, 28)
        session_date = date(year, mon, day_num).strftime("%Y-%m-%d")

        # pick random timetable slot
        subject, teacher, start_time, end_time = random.choice(slots)

        # session timestamp (use start_time)
        ts = f"{session_date} {start_time}:00"

        # This session key makes it unique (date+subject+start_time)
        session_key = f"{session_date}_{subject}_{start_time}"

        # check if already created session in attendance
        c.execute("""
            SELECT COUNT(*) FROM attendance
            WHERE substr(timestamp,1,10)=? AND subject=? AND IFNULL(start_time,'')=?
        """, (session_date, subject, start_time))
        exists = c.fetchone()[0]

        if exists > 0:
            continue  # skip duplicate session

        created_sessions += 1

        # Decide who is present in this session
        total_students = len(students)
        present_count = max(1, int((present_percent / 100) * total_students))
        present_students = random.sample(students, min(present_count, total_students))

        for roll, name in present_students:
            # Insert attendance
            c.execute("""
                INSERT INTO attendance (student_id, name, subject, teacher, start_time, end_time, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (str(roll), name, subject, teacher, start_time, end_time, ts))
            created_attendance += 1

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "month": month,
        "sessions_requested": sessions_count,
        "sessions_created": created_sessions,
        "attendance_rows_created": created_attendance
    })


@app.route("/defaulters_page")
@admin_required
def defaulters_page():
    return render_template("defaulters.html")

@app.route("/download_defaulters_csv")
@admin_required
def download_defaulters_csv():
    month = request.args.get("month")  # YYYY-MM
    threshold = float(request.args.get("threshold", 75))

    if not month:
        month = date.today().strftime("%Y-%m")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # total sessions in month
    c.execute("""
        SELECT COUNT(DISTINCT substr(timestamp,1,10) || '_' || subject || '_' || IFNULL(start_time,''))
        FROM attendance
        WHERE substr(timestamp,1,7)=?
          AND subject IS NOT NULL
    """, (month,))
    total_sessions = c.fetchone()[0] or 0

    if total_sessions == 0:
        conn.close()
        return jsonify({"error": "No sessions found for this month"}), 400

    # attendance count per student
    c.execute("""
        SELECT student_id, COUNT(*) as attended
        FROM attendance
        WHERE substr(timestamp,1,7)=?
        GROUP BY student_id
    """, (month,))
    attendance_rows = c.fetchall()
    attended_map = {str(r[0]): int(r[1]) for r in attendance_rows}

    # all students
    c.execute("SELECT roll, name FROM students")
    students = c.fetchall()
    conn.close()

    # build defaulters list
    defaulters = []
    for roll, name in students:
        roll_str = str(roll)
        attended = attended_map.get(roll_str, 0)
        percent = (attended / total_sessions) * 100

        if percent < threshold:
            defaulters.append((roll_str, name, attended, total_sessions, round(percent, 2)))

    # create CSV
    output = io.StringIO()
    output.write("Monthly Defaulters Report\n")
    output.write(f"Month,{month}\n")
    output.write(f"Threshold,{threshold}%\n")
    output.write(f"Total Sessions,{total_sessions}\n\n")
    output.write("Roll,Name,Attended,Total Sessions,Percentage\n")

    for r in defaulters:
        roll, name, attended, total_s, perc = r
        name_safe = '"' + str(name).replace('"', '""') + '"'
        output.write(f"{roll},{name_safe},{attended},{total_s},{perc}\n")

    mem = io.BytesIO()
    mem.write(output.getvalue().encode("utf-8"))
    mem.seek(0)

    filename = f"Defaulters_{month}.csv"
    return send_file(mem, as_attachment=True, download_name=filename, mimetype="text/csv")


# -------- CSV download --------
@app.route("/download_csv", methods=["GET"])
def download_csv():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ✅ Fetch one attendance per student per day
    c.execute("""
        SELECT a.student_id, a.name, substr(a.timestamp, 1, 10) as date_str, MAX(a.timestamp) as latest_ts
        FROM attendance a
        JOIN students s ON a.student_id = s.roll
        GROUP BY a.student_id, date_str
        ORDER BY date_str DESC, a.name ASC
    """)
    rows = c.fetchall()
    conn.close()

    # ✅ Organize attendance by date
    attendance_by_date = {}
    for r in rows:
        date_str = r[2]
        if date_str not in attendance_by_date:
            attendance_by_date[date_str] = []
        attendance_by_date[date_str].append({
            "roll": r[0],
            "name": r[1],
            "timestamp": r[3]
        })

    # ✅ Write formatted CSV
    output = io.StringIO()
    output.write("Facial Recognition Attendance Report\n")
    output.write("Generated on: " + datetime.now().strftime("%d-%b-%Y %I:%M %p") + "\n\n")

    for date_str, records in attendance_by_date.items():
        date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%b-%Y")
        output.write(f"Date: {date_fmt}\n")
        output.write("Roll Number,Name,Attendance Time\n")

        for r in records:
            try:
                ts = datetime.fromisoformat(r["timestamp"])
                formatted_time = ts.strftime("%I:%M %p")
            except Exception:
                formatted_time = r["timestamp"]

            name_safe = '"' + str(r["name"]).replace('"', '""') + '"'
            output.write(f'{r["roll"]},{name_safe},{formatted_time}\n')

        output.write("\n")  # blank line after each date group

    # ✅ Return as downloadable file with readable name
    mem = io.BytesIO()
    mem.write(output.getvalue().encode("utf-8"))
    mem.seek(0)
    filename = f"Attendance_Report_{datetime.now().strftime('%d-%b-%Y')}.csv"
    return send_file(mem, as_attachment=True, download_name=filename, mimetype="text/csv")



# -------- Students API for listing/editing --------
@app.route("/students", methods=["GET"])
def students_list():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, roll, class, section, reg_no, created_at FROM students ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    data = [
        {"id": r[0], "name": r[1], "roll": r[2], "class": r[3], "section": r[4], "reg_no": r[5], "created_at": r[6]}
        for r in rows
    ]
    return jsonify({"students": data})


@app.route("/students/<int:sid>", methods=["DELETE"])
def delete_student(sid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # fetch roll first
    c.execute("SELECT roll FROM students WHERE id=?", (sid,))
    row = c.fetchone()
    if row:
        roll = row[0]
    else:
        roll = None

    c.execute("DELETE FROM students WHERE id=?", (sid,))
    c.execute("DELETE FROM attendance WHERE student_id=?", (roll if roll is not None else str(sid),))
    conn.commit()
    conn.close()

    # also delete dataset folder by roll
    if roll:
        folder = os.path.join(DATASET_DIR, str(roll))
        if os.path.isdir(folder):
            import shutil

            shutil.rmtree(folder, ignore_errors=True)

    return jsonify({"deleted": True})


@app.route("/system_status")
def system_status():
    import os
    import pandas as pd
    from datetime import datetime
    csv_path = os.path.join("encodings.csv")
    enc_count = 0
    last_update = "N/A"
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        enc_count = len(df)
        last_update = datetime.fromtimestamp(os.path.getmtime(csv_path)).strftime("%d-%b %I:%M %p")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM students")
    student_count = c.fetchone()[0]
    conn.close()

    return jsonify({
        "students": student_count,
        "encodings": enc_count,
        "last_update": last_update
    })


@app.route("/today_attendance")
def today_attendance():
    import sqlite3
    from datetime import datetime, timezone, timedelta

    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Fetch only the latest attendance record per student for today
    c.execute("""
        SELECT s.name, s.roll
        FROM attendance a
        JOIN students s ON a.student_id = s.roll
        WHERE date(a.timestamp) = ?
        GROUP BY s.roll
        ORDER BY MAX(a.timestamp) DESC
    """, (today,))

    rows = c.fetchall()
    conn.close()

    data = [{"name": r[0], "roll": r[1]} for r in rows]
    return jsonify({"records": data})



# ---------------- run ------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)