from flask import Flask, redirect, render_template, request, url_for

from sync_survey import SyncError, add_survey_config, load_config, run_sync

app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
def index():
    message = None
    error = None
    results = None

    if request.method == "POST":
        try:
            summary = run_sync()
            message = summary["message"]
            results = summary.get("synced", [])
        except SyncError as exc:
            error = str(exc)

    return render_template("index.html", message=message, error=error, results=results)


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    success = None

    if request.method == "POST":
        entry = {
            "client": request.form.get("client", "").strip(),
            "course": request.form.get("course", "").strip(),
            "manager": request.form.get("manager", "").strip(),
            "date": request.form.get("date", "").strip(),
            "category": request.form.get("category", "").strip(),
            "survey_name": request.form.get("survey_name", "").strip(),
            "sheet_url": request.form.get("sheet_url", "").strip(),
        }
        try:
            updated = add_survey_config(entry)
            success = "설문 정보가 업데이트되었습니다." if updated else "설문 정보가 등록되었습니다."
        except SyncError as exc:
            error = str(exc)

    return render_template("register.html", error=error, success=success)


@app.route("/config")
def config_view():
    data = load_config("forms_config.json")
    return render_template("config.html", data=data)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
