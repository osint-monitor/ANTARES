# Importazioni per l'app web
import os
import json
import io
import uuid
from datetime import datetime, timezone
import re
import sqlite3
from dotenv import load_dotenv
from flask import (
    Response, session, stream_with_context, render_template, request, 
    json, jsonify, Flask, make_response, flash, redirect, url_for, 
    send_file, send_from_directory, abort
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_babel import Babel, gettext as _
from sentence_transformers import SentenceTransformer, util

# Modelli e utility custom
from database import (
    init_db, add_task, get_task_status, get_all_tasks,
    add_group, get_all_groups, get_group, update_group_status, get_tasks_by_group
)
from pdf_generator import generate_task_pdf, generate_group_pdf
from misp_generator import generate_misp_event

app = Flask(__name__)

DB_NAME = 'antares.db'
init_db()

# Reindirizza il traffico verso ANTARES
application = DispatcherMiddleware(
    Response('Not Found', status=404),
    {
        '/ANTARES': app
    }
)

load_dotenv()

app.config['SECRET_KEY'] = os.getenv("FLASK_SECRET_KEY")
limiter = Limiter(get_remote_address, app=app, default_limits=[])

# Caricamento condizionale delle rotte admin (file non versionato su Git)
try:
    from admin_routes import register_admin_routes
    register_admin_routes(app, limiter)
    print("[*] Rotte admin caricate.")
except ImportError:
    print("[!] admin_routes.py non trovato: rotta admin disabilitata in questo ambiente.")

# Function to retrieve profiles of APT, State Groups, etc...
def get_profiles():
    profiles = {}
    # Recupera la lingua attiva da Babel o fallback su 'it'
    lang = current_lang()

    profiles_dir = os.path.join('profiles', lang)

    # Fallback sulla cartella 'it' se la sottocartella della lingua non esiste
    if not os.path.exists(profiles_dir):
        profiles_dir = os.path.join('profiles', 'it')

    if os.path.exists(profiles_dir):
        for filename in os.listdir(profiles_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(profiles_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        actor_id = filename.replace('.json', '')
                        profiles[actor_id] = json.load(f)
                except Exception as e:
                    print(f"Errore caricamento {filename}: {e}")
    return profiles



# Configurazione Flask-Babel
def get_locale():
    if 'lang' in session:
        return session['lang']
    return 'en'

babel = Babel(app, locale_selector=get_locale)


def current_lang():
    """Lingua attiva (IT/EN), usata anche per la localizzazione dei PDF.
    Centralizza la stessa logica di fallback già usata in get_profiles()/new_task().
    """
    try:
        lang = str(get_locale()) if get_locale() else session.get('lang', 'it')
    except Exception:
        lang = session.get('lang', 'it')
    return lang if lang in ('it', 'en') else 'it'


# ==========================================
# SUGGERIMENTO ATTORE (ANALISI DI AFFINITA' SEMANTICA)
# ==========================================

# Caricamento del modello di embedding all'avvio dell'app (gira su CPU)
print("[*] Caricamento modello di embedding (MiniLM)...")
embedder = SentenceTransformer('all-MiniLM-L6-v2')

# Cache degli embedding degli attori, tenuta separata per lingua: i profili in
# /profiles/<lang> hanno testi diversi (IT/EN) quindi anche gli embedding differiscono.
_actor_embeddings_cache = {}


def _profile_text_for_embedding(data):
    """Costruisce il testo da vettorizzare per un attore, supportando sia le chiavi
    italiane sia quelle inglesi eventualmente presenti nei file profilo."""
    if not isinstance(data, dict):
        return ""

    tono = data.get('tono_narrativo', '') or data.get('narrative_tone', '')

    targeting = data.get('targeting_cognitivo', '')
    if not targeting:
        target_sectors = data.get('target_sectors')
        if isinstance(target_sectors, list):
            targeting = " ".join(str(t) for t in target_sectors)
        elif target_sectors:
            targeting = str(target_sectors)

    obiettivi = data.get('obiettivi_strategici_permanenti', []) or data.get('strategic_objectives', [])
    if isinstance(obiettivi, list):
        obiettivi = " ".join(str(o) for o in obiettivi)

    descrizione = data.get('descrizione') or data.get('description') or data.get('overview') or ''

    return f"{tono} {targeting} {obiettivi} {descrizione}".strip()


def get_actor_embeddings(lang):
    """Ritorna gli embedding degli attori per la lingua indicata, calcolandoli
    (e mettendoli in cache) al primo utilizzo."""
    if lang in _actor_embeddings_cache:
        return _actor_embeddings_cache[lang]

    print(f"[*] Generazione matrici cognitive degli attori (lingua: {lang})...")
    profiles = get_profiles() 
    embeddings_db = {}
    for actor_id, data in profiles.items():
        text_to_embed = _profile_text_for_embedding(data)
        embeddings_db[actor_id] = embedder.encode(text_to_embed, convert_to_tensor=True)

    _actor_embeddings_cache[lang] = embeddings_db
    return embeddings_db


@app.route('/api/suggest-actor', methods=['POST'])
def api_suggest_actor():
    """Suggerisce i 3 threat actor più affini semanticamente al testo inserito."""
    data = request.get_json(silent=True) or {}
    fact = (data.get('fact') or data.get('news_text') or '').strip()

    if not fact:
        return jsonify({"error": _("Nessun testo fornito")}), 400

    lang = current_lang()
    actor_embeddings = get_actor_embeddings(lang)
    profiles = get_profiles()

    if not actor_embeddings:
        return jsonify({"suggestions": []})

    fact_emb = embedder.encode(fact, convert_to_tensor=True)

    results = []
    for actor_id, actor_emb in actor_embeddings.items():
        score = util.cos_sim(fact_emb, actor_emb).item()
        profile = profiles.get(actor_id, {})
        name = (profile.get('nome') or profile.get('name') or actor_id) if isinstance(profile, dict) else actor_id
        results.append({
            "actor_id": actor_id,
            "name": name,
            "score": round(score * 100, 1)
        })

    results = sorted(results, key=lambda x: x['score'], reverse=True)
    return jsonify({"suggestions": results[:3]})


# ==========================================
# ROTTE DI INTERFACCIA
# ==========================================
@app.route('/')
def index():
    return render_template("index.html")

@app.route('/dashboard', methods=['GET'])
def dashboard():
    all_tasks = get_all_tasks()
    groups = get_all_groups()
    
    group_tasks = {}
    orphan_tasks = []
    
    for t in all_tasks:
        t_dict = dict(t) if hasattr(t, 'keys') else t
        if t_dict.get('group_id'):
            gid = t_dict['group_id']
            group_tasks.setdefault(gid, []).append(t_dict)
        else:
            orphan_tasks.append(t_dict)
    
    return render_template(
        'dashboard.html', 
        groups=groups, 
        group_tasks=group_tasks, 
        orphan_tasks=orphan_tasks
    )

@app.route('/new_task', methods=['GET', 'POST'])
def new_task():

    # Verifica stato admin dalla sessione
    is_admin = session.get('is_admin', False)

    if request.method == 'POST':
        # BLOCCO DEMO MODE: se non sei admin, rifiuta la richiesta
        if not is_admin:
            if request.is_json:
                return jsonify({"error": "Modalità Demo (Sola Lettura): Creazione di nuovi task disabilitata."}), 403
            flash(_("Modalità Demo: impossibile avviare nuove analisi. Esplora le dashboard o la Threat Library."), "warning")
            return redirect(url_for('new_task'))
        
        if request.is_json:
            data = request.get_json()
            fact_text = data.get('news_text', '').strip()
            primary_actor = data.get('primary_actor')
            ai_model = data.get('ai_model', 'gemini_api')
            additional_actors = data.get('additional_actors', [])
        else:
            fact_text = request.form.get('news_text', '').strip()
            primary_actor = request.form.get('primary_actor')
            ai_model = request.form.get('ai_model', 'gemini_api')
            additional_actors = request.form.getlist('additional_actors')

        task_lang = current_lang()

        if not fact_text or not primary_actor:
            if request.is_json:
                return jsonify({"error": _("Testo e attore principale obbligatori")}), 400
            flash(_("Compila tutti i campi obbligatori."), "warning")
            return redirect(url_for('new_task'))

        if ai_model == 'local_model':
            backend = 'local'
            model_file = 'Qwen2.5-7B-Instruct-Q4_K_M.gguf'
        else:
            backend = 'gemini'
            model_file = None

        additional_actors = [actor for actor in additional_actors if actor != primary_actor][:3]

        if additional_actors:
            group_id = str(uuid.uuid4())
            preview = fact_text[:120] + "..." if len(fact_text) > 120 else fact_text
            actor_count = len(additional_actors) + 1

            add_group(group_id, None, preview, actor_count)
            base_task_id = add_task(fact_text, primary_actor, backend=backend, model_file=model_file, group_id=group_id, lang=task_lang)
            for actor in additional_actors:
                add_task(fact_text, actor, backend=backend, model_file=model_file, group_id=group_id, lang=task_lang)

            if request.is_json:
                return jsonify({"message": "Gruppo creato", "group_id": group_id, "base_task_id": base_task_id})
            return redirect(url_for('show_compare', group_id=group_id))

        else:
            task_id = add_task(fact_text, primary_actor, backend=backend, model_file=model_file, lang=task_lang)
            if request.is_json:
                return jsonify({"message": "Task creato", "task_id": task_id})
            return redirect(url_for('show_status_page', task_id=task_id))

    # Passiamo il dizionario dei profili caricati dalla cartella /profiles al template
    profiles = get_profiles()
    return render_template('new_task.html', current_locale=str(get_locale()), profiles=profiles, is_admin=is_admin)

@app.route('/api/actors', methods=['GET'])
def api_get_actors():
    """Endpoint API per recuperare la lista dei profili caricati da /profiles"""
    return jsonify(get_profiles())


# Rotta per la Threat Intel Library
@app.route('/intel', methods=['GET'])
def threat_intel_library():
    try:
        # Recupera tutti i profili JSON
        all_profiles = get_profiles()
        
        # Ordina alfabeticamente in base alla chiave per avere una sidebar ordinata
        sorted_profiles = dict(sorted(all_profiles.items()))
        
        return render_template('intel.html', profiles=sorted_profiles)
    except Exception as e:
        abort(500, description=f"Errore nel caricamento della libreria Intel: {str(e)}")


# Rotta per Architecture
@app.route('/architecture', methods=['GET'])
def architecture():
    return render_template("architecture.html")

# Rotta per About
@app.route('/about', methods=['GET'])
def about():
    return render_template("about.html")


@app.route('/status/<int:task_id>', methods=['GET'])
def show_status_page(task_id):
    return render_template('status.html', task_id=task_id)


@app.route('/set_language/<lang>')
def set_language(lang):
    if lang in ['it', 'en']:
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))


# ==========================================
# ROTTE API (REST & POLLING)
# ==========================================

@app.route('/api/task/<int:task_id>')
def api_check_status(task_id):
    try:
        task = get_task_status(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        
        t_dict = dict(task) if hasattr(task, 'keys') else (task if isinstance(task, dict) else {})
        db_result = t_dict.get("result_text") or t_dict.get("result") or ""

        return jsonify({
            "status": t_dict.get("status", "unknown"),
            "result": db_result,
            "blue_team_result": t_dict.get("blue_team_result") or "",
            "fact_text": t_dict.get("fact_text") or "",
            "actor_id": t_dict.get("actor_id") or "",
            "started_at": t_dict.get("started_at") or "",
            "completed_at": t_dict.get("completed_at") or "",
            "backend": t_dict.get("backend", "local"),
            "group_id": t_dict.get("group_id") or None
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "result": f"Errore interno API del server: {str(e)}"
        }), 200


# Reindirizza la pagina di confronto per un gruppo specifico
@app.route('/compare/<group_id>')
def show_compare(group_id):
    return render_template('compare.html', group_id=group_id)


@app.route('/api/group/<group_id>')
def api_group_status(group_id):
    # Sincronizza stato gruppo prima di rispondere
    update_group_status(group_id)
    
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM tasks WHERE group_id = ? ORDER BY id ASC", (group_id,))
    rows = c.fetchall()
    conn.close()

    tasks = [dict(row) for row in rows]
    return jsonify({"tasks": tasks})




@app.route('/api/export/stix/<int:task_id>', methods=['GET'])
def export_stix(task_id):
    try:
        task = get_task_status(task_id)
        if not task:
            return jsonify({"error": "Task non trovato"}), 404
            
        t_dict = dict(task) if hasattr(task, 'keys') else (task if isinstance(task, dict) else {})
        red_json_str = t_dict.get("result_text") or t_dict.get("result") or ""
        actor_id = t_dict.get("actor_id", "Unknown")
        fact_text = t_dict.get("fact_text", "")

        if not red_json_str:
            return jsonify({"error": "Analisi non ancora completata."}), 400

        clean_json = red_json_str.replace("```json", "").replace("```", "").strip()
        start_idx = clean_json.find('{')
        end_idx = clean_json.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            clean_json = clean_json[start_idx:end_idx+1]
            
        try:
            red_data = json.loads(clean_json)
        except Exception:
            red_data = {}

        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        bundle_id = f"bundle--{uuid.uuid4()}"
        actor_uuid = f"threat-actor--{uuid.uuid4()}"
        report_uuid = f"report--{uuid.uuid4()}"

        stix_bundle = {
            "type": "bundle",
            "id": bundle_id,
            "objects": [
                {
                    "type": "threat-actor",
                    "spec_version": "2.1",
                    "id": actor_uuid,
                    "created": timestamp,
                    "modified": timestamp,
                    "name": actor_id.upper(),
                    "description": "Attore ostile profilato nel sistema ANTARES.",
                    "roles": ["disinformation-actor"]
                },
                {
                    "type": "report",
                    "spec_version": "2.1",
                    "id": report_uuid,
                    "created": timestamp,
                    "modified": timestamp,
                    "name": f"Analisi FIMI ANTARES - Task #{task_id}",
                    "description": red_data.get("psyops_objectives", "Analisi di Weaponization Cognitiva."),
                    "published": timestamp,
                    "object_refs": [actor_uuid],
                    "external_references": [
                        {
                            "source_name": "Testo Origine Analizzato",
                            "description": fact_text[:300] + "..." if len(fact_text) > 300 else fact_text
                        },
                        {
                            "source_name": "Social Payload Generato",
                            "description": red_data.get("social_payload", "N/D")
                        }
                    ]
                }
            ]
        }

        techniques_str = red_data.get("disarm_techniques", "")
        matches = list(re.finditer(r'(T\d{4})(.*?)(?=(T\d{4})|$)', techniques_str, re.DOTALL))
        
        if matches:
            for match in matches:
                tech_id = match.group(1).strip()
                tech_desc = match.group(2).strip(' -.,()')
                ap_uuid = f"attack-pattern--{uuid.uuid4()}"
                ap_obj = {
                    "type": "attack-pattern",
                    "spec_version": "2.1",
                    "id": ap_uuid,
                    "created": timestamp,
                    "modified": timestamp,
                    "name": f"DISARM {tech_id}",
                    "description": tech_desc if tech_desc else f"Tecnica DISARM {tech_id} identificata dall'IA",
                    "external_references": [{"source_name": "DISARM Framework", "external_id": tech_id}]
                }
                rel_uuid = f"relationship--{uuid.uuid4()}"
                rel_obj = {
                    "type": "relationship",
                    "spec_version": "2.1",
                    "id": rel_uuid,
                    "created": timestamp,
                    "modified": timestamp,
                    "relationship_type": "uses",
                    "source_ref": actor_uuid,
                    "target_ref": ap_uuid
                }
                stix_bundle["objects"].extend([ap_obj, rel_obj])
                stix_bundle["objects"][1]["object_refs"].extend([ap_uuid, rel_uuid])

        response = Response(json.dumps(stix_bundle, indent=4), mimetype='application/json')
        response.headers["Content-Disposition"] = f"attachment; filename=ANTARES_STIX_Task_{task_id}.json"
        return response
        
    except Exception as e:
        return jsonify({"error": f"Errore durante la generazione STIX: {str(e)}"}), 500

@app.route('/api/export/pdf/<int:task_id>', methods=['GET'])
def export_pdf(task_id):
    try:
        task = get_task_status(task_id)
        if not task:
            return jsonify({"error": "Task non trovato"}), 404

        t_dict = dict(task) if hasattr(task, 'keys') else (task if isinstance(task, dict) else {})

        if not (t_dict.get("result_text") or t_dict.get("result")):
            return jsonify({"error": "Analisi non ancora completata."}), 400

        pdf_bytes = generate_task_pdf(t_dict, task_id, lang=current_lang())

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"ANTARES_Task_{task_id}.pdf"
        )
    except Exception as e:
        return jsonify({"error": f"Errore durante la generazione del PDF: {str(e)}"}), 500

@app.route('/api/export/misp/<int:task_id>', methods=['GET'])
def export_misp(task_id):
    try:
        task = get_task_status(task_id)
        if not task:
            return jsonify({"error": "Task non trovato"}), 404

        t_dict = dict(task) if hasattr(task, 'keys') else (task if isinstance(task, dict) else {})

        if not (t_dict.get("result_text") or t_dict.get("result")):
            return jsonify({"error": "Analisi non ancora completata."}), 400

        misp_json = generate_misp_event(t_dict, task_id)

        response = Response(misp_json, mimetype='application/json')
        response.headers["Content-Disposition"] = f"attachment; filename=ANTARES_MISP_Task_{task_id}.json"
        return response

    except Exception as e:
        return jsonify({"error": f"Errore durante la generazione MISP: {str(e)}"}), 500


# Rotta per generare ed esportare la Matrice Comparativa in PDF
@app.route('/api/export/pdf-compare/<group_id>', methods=['GET'])
def export_pdf_compare(group_id):
    try:
        group = get_group(group_id)
        if not group:
            return jsonify({"error": "Gruppo non trovato"}), 404

        tasks = get_tasks_by_group(group_id)
        if not tasks:
            return jsonify({"error": "Nessun task trovato per questo gruppo"}), 404

        pdf_bytes = generate_group_pdf(tasks, group_id, group, lang=current_lang())

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"ANTARES_Matrice_{group_id[:8]}.pdf"
        )

    except Exception as e:
        return jsonify({"error": f"Errore durante la generazione del PDF comparativo: {str(e)}"}), 500




if __name__ == '__main__':
    app.run(debug=True)
