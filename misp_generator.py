import json
import re
from datetime import datetime, timezone


def generate_misp_event(task_dict, task_id):
    """
    Genera un evento MISP 2.4+ strutturato semanticamente.
    Usa tipi attributo nativi per correlazione automatica e Object
    'microblog' (template nativo MISP) per il payload sociale.
    """
    red_json_str = task_dict.get("result_text") or task_dict.get("result") or ""
    actor_id = task_dict.get("actor_id", "Unknown")
    fact_text = task_dict.get("fact_text", "")
    blue_result = task_dict.get("blue_team_result", "")

    # --- Parsing sicuro JSON Red Team ---
    red_data = {}
    try:
        clean = red_json_str.replace("```json", "").replace("```", "").strip()
        a, b = clean.find('{'), clean.rfind('}')
        if a != -1 and b > a:
            red_data = json.loads(clean[a:b+1])
    except Exception:
        pass

    # --- Threat Level da risk_assessment ---
    threat_level = "3"  # Low
    risk_str = red_data.get("risk_assessment", "").lower()
    scores = [int(x) for x in re.findall(r'(\d)/5', risk_str)]
    max_score = max(scores) if scores else 0
    if max_score >= 4:
        threat_level = "1"  # High
    elif max_score >= 3:
        threat_level = "2"  # Medium

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    attributes = []
    objects = []

    def _add_attr(type_, category, value, comment="", to_ids=False):
        if not value or not str(value).strip():
            return
        v = str(value)
        if len(v) > 5000:
            v = v[:4997] + "..."
        attributes.append({
            "type": type_,
            "category": category,
            "value": v,
            "comment": comment,
            "to_ids": to_ids,
            "distribution": "1"
        })

    # =====================================================================
    # ATTRIBUTI NATIVI MISP (pivotabili e correlabili)
    # =====================================================================

    # 1. Attribution — tipo nativo MISP, pivotabile con altri eventi
    _add_attr(
        "threat-actor",
        "Attribution",
        actor_id.upper(),
        "Attore ostile profilato nel sistema ANTARES"
    )

    # 2. Target Audience — tipo semantico nativo per targeting
    if red_data.get("target_audience_analysis"):
        _add_attr(
            "target-external",
            "Targeting data",
            red_data["target_audience_analysis"],
            "Target Audience identificata dal Red Team"
        )

    # 3. Indicatori di amplificazione — 'comment' è il tipo nativo MISP
    #    per indicatori deboli, keyword, hashtag (non IOC tecnici)
    if red_data.get("indicators_of_influence"):
        _add_attr(
            "comment",
            "Network activity",
            red_data["indicators_of_influence"],
            "Hashtag / keyword di amplificazione previsti"
        )

    # 4. Tecniche DISARM — comment con riferimento framework
    if red_data.get("disarm_techniques"):
        _add_attr(
            "comment",
            "External analysis",
            red_data["disarm_techniques"],
            "Tecniche DISARM/AMITT identificate"
        )

    # 5. Testo origine — text è accettabile per documenti lunghi
    if fact_text:
        _add_attr(
            "text",
            "External analysis",
            fact_text,
            "Testo origine analizzato"
        )

    # 6. PSYOPS Objectives
    if red_data.get("psyops_objectives"):
        _add_attr(
            "text",
            "External analysis",
            red_data["psyops_objectives"],
            "Obiettivi PSYOPS"
        )

    # 7. Risk Assessment
    if red_data.get("risk_assessment"):
        _add_attr(
            "text",
            "External analysis",
            red_data["risk_assessment"],
            "Valutazione rischio Virulenza/Impatto"
        )

    # 8. Weak spots
    if red_data.get("weak_spots"):
        _add_attr(
            "text",
            "External analysis",
            red_data["weak_spots"],
            "Punti deboli dell'attore nello scenario"
        )

    # 9. Blue Team Playbook
    if blue_result:
        _add_attr(
            "text",
            "External analysis",
            blue_result,
            "Playbook di contrasto Blue Team"
        )

    # =====================================================================
    # OBJECT NATIVO MISP: microblog
    # =====================================================================
    # Il template 'microblog' è nativo in MISP. Permette di modellare
    # post, piattaforma, autore, link e allegati in un oggetto strutturato
    # che MISP sa renderizzare e correlare con altri eventi FIMI.
    if red_data.get("social_payload"):
        payload = str(red_data["social_payload"])
        platform = "Social Media"
        p_low = payload.lower()
        if "telegram" in p_low:
            platform = "Telegram"
        elif "twitter" in p_low or " x " in p_low:
            platform = "X/Twitter"

        objects.append({
            "name": "microblog",
            "meta-category": "misc",
            "description": "Social payload generato dalla simulazione Red Team",
            "Attribute": [
                {
                    "type": "text",
                    "object_relation": "post",
                    "value": payload[:4000] if len(payload) > 4000 else payload,
                    "comment": "Testo del post simulato"
                },
                {
                    "type": "text",
                    "object_relation": "platform",
                    "value": platform,
                    "comment": "Piattaforma di diffusione prevista"
                },
                {
                    "type": "text",
                    "object_relation": "display-name",
                    "value": f"ANTARES Sim — {actor_id.upper()}",
                    "comment": "Identificativo simulato del mittente"
                }
            ]
        })

    # =====================================================================
    # ASSEMBLAGGIO EVENTO
    # =====================================================================
    misp_event = {
        "Event": {
            "info": f"[ANTARES] Cognitive Analysis — Task #{task_id} | Actor: {actor_id.upper()}",
            "threat_level_id": threat_level,
            "analysis": "2",
            "distribution": "1",
            "date": today,
            "Attribute": attributes,
            "Object": objects,
            "Tag": [
                {"name": "FIMI"},
                {"name": "disinformation"},
                {"name": "cognitive-warfare"},
                {"name": "ANTARES"},
                {"name": "red-team-analysis"},
                {"name": f"actor:{actor_id.lower()}"},
                {"name": f"antares-risk:{'high' if threat_level=='1' else 'medium' if threat_level=='2' else 'low'}"}
            ]
        }
    }

    return json.dumps(misp_event, indent=4, ensure_ascii=False)