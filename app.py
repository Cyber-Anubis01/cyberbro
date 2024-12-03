import os
import json
import time
import uuid
import threading
from flask import Flask, request, render_template, jsonify, send_from_directory

from utils.utils import extract_observables, refang_text
from utils.export import prepare_data_for_export, export_to_csv, export_to_excel
from models.analysis_result import AnalysisResult, db
from utils.stats import get_analysis_stats
from utils.analysis import perform_analysis, handle_analysis_completion, check_analysis_in_progress

app = Flask(__name__)

# Configure database
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Ensure the data directory exists
DATA_DIR = os.path.join(BASE_DIR, 'data')
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Enable the config page - not intended for public use since authentication is not implemented
app.config['CONFIG_PAGE_ENABLED'] = False

# Load secrets from a file
SECRETS_FILE = os.path.join(BASE_DIR, 'secrets.json')
if os.path.exists(SECRETS_FILE):
    with open(SECRETS_FILE, 'r') as f:
        secrets = json.load(f)
else:
    secrets = {}

# Update the database URI to use the data directory
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(DATA_DIR, 'results.db')}"

# Initialize the database
db.init_app(app)

# Create the database tables if they do not exist
with app.app_context():
    db.create_all()

@app.route('/')
def index():
    """Render the index page."""
    return render_template('index.html', results=[])

@app.route('/analyze', methods=['POST'])
def analyze():
    """Handle the analyze request."""
    form_data = refang_text(request.form.get("observables", ""))
    observables = extract_observables(form_data)
    selected_engines = request.form.getlist("engines")

    analysis_id = str(uuid.uuid4())
    threading.Thread(target=perform_analysis, args=(observables, selected_engines, analysis_id)).start()

    return render_template('waiting.html', analysis_id=analysis_id), 200

@app.route('/results/<analysis_id>', methods=['GET'])
def show_results(analysis_id):
    """Show the results of the analysis."""
    analysis_results = db.session.get(AnalysisResult, analysis_id)
    if analysis_results:
        return render_template('index.html', analysis_results=analysis_results)
    else:
        return render_template('404.html'), 404

@app.route('/is_analysis_complete/<analysis_id>', methods=['GET'])
def is_analysis_complete(analysis_id):
    """Check if the analysis is complete."""
    complete = not check_analysis_in_progress(analysis_id)
    if complete:
        handle_analysis_completion(analysis_id)
    return jsonify({'complete': complete})

@app.route('/export/<analysis_id>')
def export(analysis_id):
    """Export the analysis results."""
    format = request.args.get('format')
    analysis_results = db.session.get(AnalysisResult, analysis_id)
    data = prepare_data_for_export(analysis_results)
    timestamp = time.strftime("%Y-%m-%d_%H_%M_%S", time.localtime())

    if format == 'csv':
        return export_to_csv(data, timestamp)
    elif format == 'excel':
        return export_to_excel(data, timestamp)

@app.route('/favicon.ico')
def favicon():
    """Serve the favicon."""
    return send_from_directory(os.path.join(app.root_path, 'images'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.errorhandler(404)
def page_not_found(e):
    """Handle 404 errors."""
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    """Handle 500 errors."""
    return render_template('500.html'), 500

# add a history page showing analysis results links
@app.route('/history')
def history():
    """Render the history page."""
    analysis_results = AnalysisResult.query.order_by(AnalysisResult.end_time.desc()).all()
    return render_template('history.html', analysis_results=analysis_results)

@app.route('/stats')
def stats():
    """Render the stats page."""
    stats = get_analysis_stats()
    return render_template('stats.html', stats=stats)

# add about page
@app.route('/about')
def about():
    """Render the about page."""
    return render_template('about.html')

# add config page
@app.route('/config')
def config():
    """Render the config page."""
    if not app.config.get('CONFIG_PAGE_ENABLED', False):
        return render_template('404.html'), 404
    return render_template('config.html', secrets=secrets)

# add update_config endpoint
@app.route('/update_config', methods=['POST'])
def update_config():
    """Update config from the form data"""
    if not app.config.get('CONFIG_PAGE_ENABLED', False):
        return jsonify({'message': 'Configuration update is disabled.'}), 403
    try:
        secrets["proxy_url"] = request.form.get("proxy_url")
        secrets["ipinfo"] = request.form.get("ipinfo")
        secrets["mde_tenant_id"] = request.form.get("mde_tenant_id")
        secrets["mde_client_id"] = request.form.get("mde_client_id")
        secrets["mde_client_secret"] = request.form.get("mde_client_secret")
        secrets["virustotal"] = request.form.get("virustotal")
        secrets["google_safe_browsing"] = request.form.get("google_safe_browsing")
        secrets["ip_quality_score"] = request.form.get("ip_quality_score")
        secrets["shodan"] = request.form.get("shodan")
        with open(SECRETS_FILE, 'w') as f:
            json.dump(secrets, f, indent=4)
        message = "Configuration updated successfully."
    except Exception as e:
        message = "An error occurred while updating the configuration."
    return jsonify({'message': message})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
