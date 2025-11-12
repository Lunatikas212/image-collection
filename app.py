from flask import Flask, request, render_template_string, redirect, url_for
from PIL import Image
import imagehash
import os
import csv
import uuid
from datetime import datetime
from shutil import copy2

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
DATASET_FOLDER = "dataset"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DATASET_FOLDER, exist_ok=True)

DATA_CSV = os.path.join(os.path.dirname(__file__), "data.csv")
METADATA_CSV = os.path.join(DATASET_FOLDER, "metadata.csv")
HISTORY_CSV = os.path.join(DATASET_FOLDER, "edit_history.csv")

hashes = {}
uploaders = {}
if os.path.exists(DATA_CSV):
    with open(DATA_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            hashes[imagehash.hex_to_hash(row["hash"])] = row["new_filename"]
            uploaders[row["new_filename"]] = row.get("uploader_ip", "unknown")

def next_filename():
    existing = [f for f in os.listdir(DATASET_FOLDER) if f.endswith(".jpg")]
    numbers = [int(os.path.splitext(f)[0]) for f in existing if f.split('.')[0].isdigit()]
    return f"{(max(numbers)+1) if numbers else 1:02d}.jpg"

UPLOAD_HTML = """
<!doctype html>
<html lang="en">
<head><title>Upload Photos with Description</title></head>
<body>
<h2>Upload Photos with Descriptions</h2>
<form method="post" action="/upload" enctype="multipart/form-data">
  <input type="file" name="files" id="files" multiple onchange="addDescriptionInputs()"><br><br>
  <div id="descriptions"></div><br>
  <input type="submit" value="Upload">
</form>
<br>
<a href="/edit">Edit Existing Descriptions</a>
<script>
function addDescriptionInputs() {
    let filesInput = document.getElementById('files');
    let container = document.getElementById('descriptions');
    container.innerHTML = '';
    for (let i = 0; i < filesInput.files.length; i++) {
        let file = filesInput.files[i];
        let div = document.createElement('div');
        div.innerHTML = file.name + ': <input type="text" name="desc_' + i + '" placeholder="Description">';
        container.appendChild(div);
    }
}
</script>
{% if results %}
<h3>Results:</h3>
<ul>
{% for r in results %}
    <li>{{ r }}</li>
{% endfor %}
</ul>
{% endif %}
</body>
</html>
"""

class HistoryEntry:
    def __init__(self, description, editor_ip, timestamp):
        self.description = description
        self.editor_ip = editor_ip
        self.timestamp = timestamp

@app.route("/", methods=["GET"])
def index():
    return render_template_string(UPLOAD_HTML, results=None)

@app.route("/upload", methods=["POST"])
def upload():
    uploaded_files = request.files.getlist("files")
    results = []

    descriptions = []
    for key in sorted(request.form.keys()):
        if key.startswith("desc_"):
            descriptions.append(request.form[key])

    uploader_ip = request.remote_addr

    for idx, file in enumerate(uploaded_files):
        if file.filename == '':
            continue
        if not file.filename.lower().endswith((".jpg", ".jpeg", ".png")):
            results.append(f"{file.filename} → skipped (not an image)")
            continue

        temp_path = os.path.join(UPLOAD_FOLDER, str(uuid.uuid4()) + "_" + file.filename)
        file.save(temp_path)

        img = Image.open(temp_path)
        phash = imagehash.phash(img)

        duplicate = False
        for existing_hash, existing_file in hashes.items():
            if abs(phash - existing_hash) < 5:
                duplicate = True
                results.append(f"{file.filename} → duplicate of {existing_file}")
                break

        if not duplicate:
            new_name = next_filename()
            save_path = os.path.join(DATASET_FOLDER, new_name)
            img.save(save_path)

            file_exists = os.path.exists(DATA_CSV)
            with open(DATA_CSV, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["original_filename", "hash", "new_filename", "uploader_ip"])
                if not file_exists:
                    writer.writeheader()
                writer.writerow({
                    "original_filename": file.filename,
                    "hash": str(phash),
                    "new_filename": new_name,
                    "uploader_ip": uploader_ip
                })
            hashes[phash] = new_name
            uploaders[new_name] = uploader_ip

            description = descriptions[idx] if idx < len(descriptions) else ""
            meta_exists = os.path.exists(METADATA_CSV)
            with open(METADATA_CSV, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["file_name", "description"])
                if not meta_exists:
                    writer.writeheader()
                writer.writerow({"file_name": new_name, "description": description})

            hist_exists = os.path.exists(HISTORY_CSV)
            with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["file_name", "description", "editor_ip", "timestamp"])
                if not hist_exists:
                    writer.writeheader()
                writer.writerow({
                    "file_name": new_name,
                    "description": description,
                    "editor_ip": uploader_ip,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })

            results.append(f"{file.filename} → saved as {new_name} with description: {description}")

        os.remove(temp_path)

    return render_template_string(UPLOAD_HTML, results=results)

@app.route("/edit", methods=["GET", "POST"])
def edit():
    goal = 1700

    metadata = {}
    if os.path.exists(METADATA_CSV):
        with open(METADATA_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                metadata[row["file_name"]] = row["description"]

    editor_ip = request.remote_addr
    if request.method == "POST":
        for file_name in metadata:
            if f"desc_{file_name}" in request.form:
                new_desc = request.form[f"desc_{file_name}"]
                if metadata[file_name] != new_desc:
                    metadata[file_name] = new_desc
                    hist_exists = os.path.exists(HISTORY_CSV)
                    with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=["file_name", "description", "editor_ip", "timestamp"])
                        if not hist_exists:
                            writer.writeheader()
                        writer.writerow({
                            "file_name": file_name,
                            "description": new_desc,
                            "editor_ip": editor_ip,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
        with open(METADATA_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["file_name", "description"])
            writer.writeheader()
            for fname, desc in metadata.items():
                writer.writerow({"file_name": fname, "description": desc})

        return redirect(url_for('edit'))

    history = {}
    description_edits = {}
    if os.path.exists(HISTORY_CSV):
        with open(HISTORY_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                desc = (row.get("description") or "").strip()
                editor_ip = row.get("editor_ip", "unknown")
                timestamp = row.get("timestamp", "")
                entry = HistoryEntry(desc, editor_ip, timestamp)
                history.setdefault(row.get("file_name", "unknown"), []).append(entry)
                if desc:
                    description_edits[editor_ip] = description_edits.get(editor_ip, 0) + 1

    uploads_per_ip = {}
    if os.path.exists(DATA_CSV):
        with open(DATA_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ip = row.get("uploader_ip", "unknown")
                uploads_per_ip[ip] = uploads_per_ip.get(ip, 0) + 1

    leaderboard = {}
    all_ips = set(uploads_per_ip.keys()).union(description_edits.keys())
    for ip in all_ips:
        leaderboard[ip] = {
            "uploads": uploads_per_ip.get(ip, 0),
            "edits": description_edits.get(ip, 0),
            "total": uploads_per_ip.get(ip, 0) + description_edits.get(ip, 0)
        }

    static_folder = os.path.join(app.root_path, 'static')
    os.makedirs(static_folder, exist_ok=True)
    for file_name in metadata:
        src = os.path.join(DATASET_FOLDER, file_name)
        dst = os.path.join(static_folder, file_name)
        if not os.path.exists(dst):
            try:
                copy2(src, dst)
            except:
                pass

    data_list = []
    for f in sorted(metadata.keys()):
        last_edit = history[f][-1].timestamp + " by " + history[f][-1].editor_ip if f in history else "Never"
        hist_list = history.get(f, [])
        data_list.append((f, metadata[f], uploaders.get(f, "unknown"), last_edit, hist_list))

    images_done = len(metadata)
    descriptions_done = len([d for d in metadata.values() if d.strip() != ""])

    return render_template_string("""
<!doctype html>
<html lang="en">
<head><title>Edit Descriptions & Leaderboard</title></head>
<body>
<h2>Edit Photo Descriptions</h2>

<h3>Progress</h3>
<p>Images: {{images_done}}/{{goal}}</p>
<p>Descriptions: {{descriptions_done}}/{{goal}}</p>

<h3>Leaderboard</h3>
<table border="1" cellpadding="5">
<tr><th>IP</th><th>Uploads</th><th>Description Edits</th><th>Total Contributions</th></tr>
{% for ip, stats in leaderboard.items() %}
<tr>
    <td>{{ ip }}</td>
    <td>{{ stats.uploads }}</td>
    <td>{{ stats.edits }}</td>
    <td>{{ stats.total }}</td>
</tr>
{% endfor %}
</table>

<form method="post" action="/edit">
<table border="1" cellpadding="5">
<tr><th>Photo</th><th>Description</th><th>Uploader IP</th><th>Last Edited</th><th>History</th></tr>
{% for img, desc, uploader, last_edit, history_list in data %}
<tr>
    <td><img src="{{ url_for('static', filename=img) }}" width="100"></td>
    <td><input type="text" name="desc_{{ img }}" value="{{ desc }}" size="50"></td>
    <td>{{ uploader }}</td>
    <td>{{ last_edit }}</td>
    <td>
        <ul>
        {% for h in history_list %}
            <li>{{ h.timestamp }} by {{ h.editor_ip }}: {{ h.description }}</li>
        {% endfor %}
        </ul>
    </td>
</tr>
{% endfor %}
</table>
<br>
<input type="submit" value="Save Descriptions">
</form>
<br>
<a href="/">Go Back to Upload</a>
</body>
</html>
""", data=data_list, leaderboard=leaderboard, images_done=images_done,
       descriptions_done=descriptions_done, goal=goal)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
