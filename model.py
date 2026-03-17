# model.py
import os
import csv
import cv2
import numpy as np
import face_recognition
from io import BytesIO
from collections import defaultdict

# Path to CSV that holds encodings: each row -> id,name,e0,e1,...,e127
STUDENTS_CSV = os.path.join("data", "students.csv")
os.makedirs(os.path.dirname(STUDENTS_CSV), exist_ok=True)

# ---- Utility: extract a 128D face embedding ----
def extract_embedding_for_image(input_img, model_type="hog"):
    """
    Accepts:
      - a numpy image (BGR) from cv2.imread or
      - a file-like stream (werkzeug FileStorage.stream) or bytes.
    Returns:
      - 128D numpy array (float32) or None if no face detected or multiple faces detected.
    """
    try:
        # Convert input to numpy BGR image
        if isinstance(input_img, np.ndarray):
            img = input_img
        else:
            if hasattr(input_img, "read"):
                data = input_img.read()
            elif isinstance(input_img, (bytes, bytearray)):
                data = bytes(input_img)
            else:
                return None
            arr = np.frombuffer(data, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                return None

        # Convert to RGB for face_recognition
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Detect face locations
        face_locations = face_recognition.face_locations(rgb, model=model_type)
        if len(face_locations) != 1:
            # Reject if no face or multiple faces
            return None

        # Compute face encoding
        encs = face_recognition.face_encodings(rgb, face_locations)
        if len(encs) == 0:
            return None

        return np.array(encs[0], dtype=np.float32)

    except Exception as e:
        print(f"[extract_embedding_for_image] Error: {e}")
        return None


def save_student_encoding(roll, name, img_stream, model_type="hog"):
    """
    Compute embedding for the given image stream (or cv2 image) and append to STUDENTS_CSV.
    Returns True if saved, False otherwise.
    """
    try:
        emb = extract_embedding_for_image(img_stream, model_type=model_type)
        if emb is None:
            print(f"[save_student_encoding] No valid face found for {roll}")
            return False

        # Ensure CSV header exists
        header_needed = not os.path.exists(STUDENTS_CSV) or os.path.getsize(STUDENTS_CSV) == 0

        with open(STUDENTS_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if header_needed:
                hdr = ["id", "name"] + [f"e{i}" for i in range(128)]
                writer.writerow(hdr)
            row = [str(roll), str(name)] + [f"{float(x):.6f}" for x in emb.tolist()]
            writer.writerow(row)

        return True

    except Exception as e:
        print(f"[save_student_encoding] Error saving encoding: {e}")
        return False


# ---- Load all encodings into memory ----
def load_all_encodings():
    """
    Loads STUDENTS_CSV and returns:
      - ids: list of strings
      - names: list of strings
      - encodings: Nx128 numpy array (dtype=float32)
    If no file or no encodings, returns ([], [], np.empty((0,128)))
    """
    ids = []
    names = []
    embs = []

    if not os.path.exists(STUDENTS_CSV):
        return ids, names, np.empty((0, 128), dtype=np.float32)

    try:
        with open(STUDENTS_CSV, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return ids, names, np.empty((0, 128), dtype=np.float32)
            # If header present, skip first row if header contains 'id' and 'name'
            start = 0
            if rows[0] and rows[0][0].lower() == "id" and rows[0][1].lower() == "name":
                start = 1
            for r in rows[start:]:
                if len(r) < 130:
                    continue
                ids.append(str(r[0]))
                names.append(str(r[1]))
                emb = [float(x) for x in r[2:130]]
                embs.append(emb)
        if len(embs) == 0:
            return ids, names, np.empty((0, 128), dtype=np.float32)
        return ids, names, np.vstack(embs).astype(np.float32)
    except Exception as e:
        print(f"[load_all_encodings] Error: {e}")
        return [], [], np.empty((0, 128), dtype=np.float32)


# ---- Recognize face from an uploaded image stream ----
def recognize_face_from_image(img_stream, threshold=0.50):
    emb = extract_embedding_for_image(img_stream)
    if emb is None:
        return None, None, None

    ids, names, embs = load_all_encodings()
    if embs.shape[0] == 0:
        return None, None, None

    dist_map = defaultdict(list)
    name_map = {}

    for i, sid in enumerate(ids):
        d = np.linalg.norm(embs[i] - emb)
        dist_map[sid].append(d)
        name_map[sid] = names[i]

    best_id = None
    best_dist = float("inf")

    for sid, dlist in dist_map.items():
        dmin = min(dlist)
        if dmin < best_dist:
            best_dist = dmin
            best_id = sid

    if best_dist <= threshold:
        return best_id, name_map[best_id], best_dist

    return None, None, best_dist