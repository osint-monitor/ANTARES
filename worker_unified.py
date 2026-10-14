import sqlite3
import time
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from llama_cpp import Llama, LlamaRAMCache


DB_NAME = 'antares.db'

# Configurazione Gemini
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_model = "gemini-3.5-flash"
gemini_model_fallback = "gemini-2.5-flash"  # usato se si esaurisce la quota giornaliera (RPD) del modello primario


# Filtri di sicurezza disattivati per Red Teaming
from google.generativeai.types import HarmCategory, HarmBlockThreshold
safety_settings = {
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}


def _call_gemini_with_retry(model, prompt, generation_config, phase_label, max_retries=5):
    """
    Esegue generate_content gestendo il 429 (ResourceExhausted) con backoff.
    Rispetta il retry_delay suggerito dall'API quando disponibile, altrimenti
    usa un backoff esponenziale (5s, 10s, 20s, 40s, 80s...).
    """
    for attempt in range(1, max_retries + 1):
        try:
            return model.generate_content(prompt, generation_config=generation_config)
        except ResourceExhausted as e:
            # Prova a leggere il retry_delay indicato da Google, altrimenti backoff esponenziale
            retry_seconds = getattr(getattr(e, "retry_delay", None), "seconds", None)
            if not retry_seconds:
                retry_seconds = 5 * (2 ** (attempt - 1))

            if attempt >= max_retries:
                print(f"[-] [{phase_label}] Quota esaurita, tentativi massimi ({max_retries}) raggiunti. Rilancio errore.")
                raise

            print(f"[!] [{phase_label}] Rate limit (429) tentativo {attempt}/{max_retries}. "
                  f"Attendo {retry_seconds}s prima di riprovare...")
            time.sleep(retry_seconds)
    raise RuntimeError(f"[{phase_label}] Retry loop terminato senza risultato")


def _check_truncation(response, text, phase_label):
    """Rileva se una risposta Gemini è stata tagliata per limite token."""
    try:
        candidate = response.candidates[0]
        finish_reason = getattr(candidate, "finish_reason", None)
        usage = getattr(response, "usage_metadata", None)
        thoughts_tok = getattr(usage, "thoughts_token_count", None) if usage else None
        output_tok = getattr(usage, "candidates_token_count", None) if usage else None
 
        print(f"[DEBUG] [{phase_label}] finish_reason={finish_reason} "
              f"thoughts_token_count={thoughts_tok} candidates_token_count={output_tok}")
 
        is_truncated = (str(finish_reason).upper().find("MAX_TOKENS") != -1) or (finish_reason == 2)
 
        if is_truncated:
            print(f"[!] ATTENZIONE: risposta {phase_label} troncata per limite token.")
            text += (f"\n\n> ⚠️ **AVVISO SISTEMA:** output troncato per limite token "
                     f"(fase {phase_label}).")
    except Exception as e:
        print(f"[DEBUG] Impossibile verificare finish_reason/usage_metadata: {e}")
    return text


# Caricamento prompt localizzato
def load_prompt(filename, lang='it', backend=''):
    base_path = os.path.join(os.path.dirname(__file__), 'prompts', lang)
    if backend == 'local':
        local_path = os.path.join(base_path, filename.replace('.txt', '_local.txt'))
        if os.path.exists(local_path):
            with open(local_path, 'r', encoding='utf-8') as f:
                return f.read()
    path = os.path.join(base_path, filename)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# Cache per modelli caricati, evita di ricaricare a ogni task
_llm_cache = {}

def get_llm_instance(model_file):
    """
    Carica il modello GGUF specificato. Usa una cache per evitare
    di ricaricare il modello se lo stesso file viene riutilizzato.
    """
    if model_file in _llm_cache:
        print(f"[*] Riutilizzo modello in cache: {model_file}")
        return _llm_cache[model_file]

    model_path = os.path.join("models", model_file)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Modello non trovato: {model_path}")

    print(f"[*] Caricamento modello GGUF: {model_file}...")
    llm = Llama(
        model_path=model_path,
        n_ctx=4096,
        n_threads=4,
        n_batch=1024,
        use_mlock=True,
        verbose=False
    )
    cache = LlamaRAMCache(capacity_bytes=512 * 1024 * 1024)
    llm.set_cache(cache)
    _llm_cache[model_file] = llm
    print(f"[+] Modello {model_file} pronto.")
    return llm


def process_pending_tasks():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT id, fact_text, actor_id, backend, model_file, lang FROM tasks WHERE status = 'pending' ORDER BY id ASC LIMIT 1")    
    task = c.fetchone()

    if not task:
        conn.close()
        return False

    task_id, fact_text, actor_id, backend, model_file, lang = task

    orario_italiano = datetime.now(ZoneInfo("Europe/Rome")).strftime('%d-%m-%Y %H:%M:%S')
    c.execute("UPDATE tasks SET status = 'processing', started_at = ? WHERE id = ?", (orario_italiano, task_id))
    conn.commit()
    
    print(f"\n[*] Task #{task_id} [{backend.upper()}] - Inizio elaborazione per attore {actor_id}...")

    # Carica il modello locale specificato dal task (se necessario)
    llm = None
    if backend == 'local':
        if not model_file:
            # Fallback se il task è vecchio o model_file è null
            model_file = "Qwen2.5-7B-Instruct-Q4_K_M.gguf"
            print(f"[!] model_file non specificato, uso fallback: {model_file}")
        try:
            llm = get_llm_instance(model_file)
        except Exception as e:
            error_msg = f"Errore caricamento modello {model_file}: {str(e)}"
            c.execute("UPDATE tasks SET status = 'error', result_text = ? WHERE id = ?", (error_msg, task_id))
            conn.commit()
            conn.close()
            return True

    try:
        profile_path = os.path.join("profiles", lang, f"{actor_id}.json")
    # Fallback su italiano se il file tradotto non esiste ancora
        if not os.path.exists(profile_path):
            profile_path = os.path.join("profiles", "it", f"{actor_id}.json")
        with open(profile_path, 'r', encoding='utf-8') as f:
            actor_data = json.load(f)


    except Exception as e:
        error_msg = f"Impossibile caricare il profilo profiles/{actor_id}.json: {str(e)}"
        c.execute("UPDATE tasks SET status = 'error', result_text = ? WHERE id = ?", (error_msg, task_id))
        conn.commit()
        conn.close()
        return True
    
    # ==========================================
    # CARICAMENTO ED ELABORAZIONE PROMPT RED TEAM
    # ==========================================
    try:
        system_prompt_red = load_prompt("system_red.txt", lang=lang, backend=backend).format(
        nome=actor_data.get('nome', 'Sconosciuto'),
        tipo=actor_data.get('tipo', 'Non specificato'),
        descrizione=actor_data.get('descrizione', ''),
        vettori_comunicativi=", ".join(actor_data.get('vettori_comunicativi', [])),
        targeting_cognitivo=actor_data.get('targeting_cognitivo', ''),
        tono_narrativo=actor_data.get('tono_narrativo', ''),
        obiettivi_strategici=", ".join(actor_data.get('obiettivi_strategici_permanenti', [])),
        tecniche_disarm=", ".join(actor_data.get('tecniche_disarm_ricorrenti', [])),
        vulnerabilita_operative=", ".join(actor_data.get('vulnerabilita_operative', []))
        )

        user_prompt_red = load_prompt("user_red.txt", lang=lang, backend=backend).format(
        nome=actor_data.get('nome', 'Sconosciuto'),
        fact_text=fact_text,
        vulnerabilita_operative=", ".join(actor_data.get('vulnerabilita_operative', []))
        )
    except Exception as e:
        print(f"[-] Errore nel parsing dei file di prompt Red Team: {e}")
        raise e

    red_team_response = ""

    # ==========================================
    # FASE 1: RED TEAM
    # ==========================================
    try:
        if backend == 'gemini':
            print("[*] Chiamata a Gemini Flash (FASE 1)...")
            model_red = genai.GenerativeModel(model_name=gemini_model, system_instruction=system_prompt_red, safety_settings=safety_settings)
            response_red = _call_gemini_with_retry(
                model_red,
                user_prompt_red,
                genai.types.GenerationConfig(response_mime_type="application/json", temperature=0.1, max_output_tokens=4000),
                "RED"
            )
            red_team_response = response_red.text
            red_team_response = _check_truncation(response_red, red_team_response, "RED")
            
            c.execute("UPDATE tasks SET result_text = ? WHERE id = ?", (red_team_response, task_id))
            conn.commit()
        
        else:  # LOCAL LLM
            '''
            print("[!] MOCK MODE: Ollama non attivo. Genero risposta simulata...")
        
            # Simuliamo un JSON di risposta perfettamente formattato
            red_team_response = """
            {
            "psyops_objectives": "Screditare le istituzioni locali e creare panico controllato sfruttando la notizia.",
            "target_audience_analysis": "Popolazione civile, fasce d'età 18-45, utenti attivi sui social media.",
            "product_development": "Campagna di disinformazione coordinata tramite bot-net e canali Telegram alternativi.",
            "social_payload": "[ALERT] ATTENZIONE: Quello che non vi dicono su quanto accaduto... #ANTARES #BreakingNews",
            "indicators_of_influence": "#ANTARES, #VeritaNascoste, #ScandaloIstituzionale",
            "disarm_techniques": "T1571 (Coordinate Malicious Influence), T1573 (Amplification via Proxy Accounts).",
            "weak_spots": "Il comunicato ufficiale smentisce categoricamente i presupposti logici di questa narrazione.",
            "risk_assessment": "Virulenza: 4/5. Impatto Strategico: 3/5. Minaccia elevata a causa del timing dell'evento."
            }
            """

            # FIXED: Salviamo il risultato del Mock nel database altrimenti la UI si rompe!
            c.execute("UPDATE tasks SET result_text = ? WHERE id = ?", (red_team_response, task_id))
            conn.commit()
            '''            
            # CODICE DA RIMETTERE SU VPS


            print("[*] Invio richiesta a llama.cpp (FASE 1) in Streaming...")
            messages_red = [
                {"role": "system", "content": system_prompt_red},
                {"role": "user", "content": user_prompt_red}
            ]
            response_stream = llm.create_chat_completion(
                messages=messages_red,
                response_format={"type": "json_object"},
                temperature=0.1,
                top_p=0.85,
                max_tokens=1200,
                stream=True
            )
            
            token_count = 0
            finish_reason_red = None
            for chunk in response_stream:
                choice = chunk["choices"][0]
                delta = choice.get("delta", {})
                if "content" in delta:
                    red_team_response += delta["content"]
                    token_count += 1
                    if token_count % 30 == 0:
                        c.execute("UPDATE tasks SET result_text = ? WHERE id = ?", (red_team_response, task_id))
                        conn.commit()
                if choice.get("finish_reason"):
                    finish_reason_red = choice["finish_reason"]
            
            if finish_reason_red == "length":
                warn = "\n\n> ⚠️ **AVVISO SISTEMA:** Output Red Team troncato per limite di lunghezza."
                red_team_response += warn
                print("[!] Red Team troncato per 'length'.")
            
            c.execute("UPDATE tasks SET result_text = ? WHERE id = ?", (red_team_response, task_id))
            conn.commit()
            
        if not red_team_response:
            raise ValueError("Output vuoto ricevuto da Red Team.")

        # ==========================================
        # FASE 2: BLUE TEAM (Preparazione dati)
        # ==========================================
        print(f"[*] FASE 1 Completata. Inizio FASE 2: Blue Team...")
        c.execute("UPDATE tasks SET status = 'processing_blue', result_text = ? WHERE id = ?", (red_team_response, task_id))
        conn.commit()

        red_parsed = {}
        try:
            clean_red = red_team_response.replace("```json", "").replace("```", "").strip()
            red_parsed = json.loads(clean_red)
        except:
            pass

        # ==========================================
        # CARICAMENTO ED ELABORAZIONE PROMPT BLUE TEAM
        # ==========================================
        try:
            system_prompt_blue = load_prompt("system_blue.txt", lang=lang, backend=backend).format(
            nome=actor_data.get('nome', 'Sconosciuto'),
            tipo=actor_data.get('tipo', 'N/D'),
            obiettivi_strategici=", ".join(actor_data.get('obiettivi_strategici_permanenti', [])),
            vettori_comunicativi=", ".join(actor_data.get('vettori_comunicativi', [])),
            vulnerabilita_operative=", ".join(actor_data.get('vulnerabilita_operative', [])),
            risk_score=red_parsed.get("risk_assessment", "Non disponibile")
            )

            user_prompt_blue = load_prompt("user_blue.txt", lang=lang, backend=backend).format(
            psyops_obj=red_parsed.get("psyops_objectives", "Non disponibile"),
            target_aud=red_parsed.get("target_audience_analysis", "Non disponibile"),
            social_pay=red_parsed.get("social_payload", "Non disponibile"),
            indicators=red_parsed.get("indicators_of_influence", "Non disponibile"),
            disarm_tech=red_parsed.get("disarm_techniques", "Non disponibile"),
            weak_spots=red_parsed.get("weak_spots", "Non disponibile"),
            fact_text=fact_text,
            nome=actor_data.get('nome', 'N/D')
            )

        except Exception as e:
            print(f"[-] Errore nel parsing dei file di prompt Blue Team: {e}")
            raise e

        blue_team_response = ""

        # ==========================================
        # FASE 2: BLUE TEAM (Esecuzione condizionale)
        # ==========================================
        if backend == 'gemini':
            print("[*] Chiamata a Gemini Flash (FASE 2)...")
            model_blue = genai.GenerativeModel(model_name=gemini_model, system_instruction=system_prompt_blue, safety_settings=safety_settings)
            response_blue = _call_gemini_with_retry(
                model_blue,
                user_prompt_blue,
                genai.types.GenerationConfig(temperature=0.25, max_output_tokens=8192),
                "BLUE"
            )
            blue_team_response = response_blue.text
            blue_team_response = _check_truncation(response_blue, blue_team_response, "BLUE")
            print(f"[DEBUG] Lunghezza testo Blue Team: {len(blue_team_response)} caratteri")
            print(f"[DEBUG] Ultimi 100 caratteri:\n{blue_team_response[-100:]}")
            print("-" * 40)
        
        else:  # LOCAL LLM
            '''
            print("[!] MOCK MODE: Ollama non attivo. Genero risposta simulata...")
        
            # Simuliamo un JSON di risposta perfettamente formattato
            blue_team_response = f"""
### 1. Valutazione Immediata della Minaccia

#### Natura dell'Operazione
Rilevata operazione ostile di tipo FIMI volta alla destabilizzazione cognitiva tramite la tecnica **{disarm_tech}**. L'attore sfrutta l'ancoraggio emotivo per polarizzare la **Target Audience**.

#### Finestra Temporale Critica
La finestra di contenimento è ristretta alle prime **2-4 ore** dalla prima occorrenza del payload sui canali social coordinati.

---

### 2. Contro-Narrativa Strategica (Prebunking)

#### Comunicato Stampa Istituzionale
"In relazione alle notizie infondate circolanti nelle ultime ore, la Presidenza del Consiglio dei Ministri precisa che i dati ufficiali confermano la totale regolarità delle procedure..."

#### Key Message di Risposta
* **Trasparenza:** Massima divulgazione dei dati di fatto verificati.
* **Smentita Attiva:** Smontare il frame *"Cosa non vi dicono"* ripristinando il contesto originale.
* **Isolamento:** Ignorare le provocazioni dirette concentrandosi sui canali certificati.

---

### 3. Direttive per i Media Mainstream
1. **Verifica alla fonte:** Non riprendere screen provenienti da canali Telegram non verificati.
2. **Fact-checking invisibile:** Smentire i presupposti della fake news senza citare il titolo clickbait avversario.

---

### 4. Piano OSINT e Monitoraggio Piattaforme
#### Piattaforme Prioritarie
Monitoraggio intensivo su **Telegram, X (Twitter) e TikTok** in virtù dei vettori d'attacco.

#### Query di Monitoraggio
`"{indicators}" AND (scandalo OR verita)`

---

### 5. Debunking Tattico (Post-Attacco)
#### Post Governativo #1 — Canale Istituzionale
*@Palazzo_Chigi: In merito alle ricostruzioni parziali diffuse sul web, si invita la cittadinanza a consultare solo i report ufficiali disponibili sul portale istituzionale. La disinformazione danneggia la sicurezza di tutti.*
            """

            
            '''      
            
            
            
            
            # CODICE DA RIMETTERE SU VPS
            print("[*] Invio richiesta a llama.cpp (FASE 2) in Streaming...")
            messages_blue = [
                {"role": "system", "content": system_prompt_blue},
                {"role": "user", "content": user_prompt_blue}
            ]
            response_stream_blue = llm.create_chat_completion(
                messages=messages_blue,
                temperature=0.25,
                top_p=0.9,
                max_tokens=2000,
                stream=True
            )
            
            token_count = 0
            finish_reason_blue = None
            for chunk in response_stream_blue:
                choice = chunk["choices"][0]
                delta = choice.get("delta", {})
                if "content" in delta:
                    blue_team_response += delta["content"]
                    token_count += 1
                    if token_count % 30 == 0:
                        c.execute("UPDATE tasks SET blue_team_result = ? WHERE id = ?", (blue_team_response, task_id))
                        conn.commit()
                if choice.get("finish_reason"):
                    finish_reason_blue = choice["finish_reason"]
            
            if finish_reason_blue == "length":
                warn = "\n\n> ⚠️ **AVVISO SISTEMA:** Output Blue Team troncato per limite di lunghezza."
                blue_team_response += warn
                print("[!] Blue Team troncato per 'length'.")

        # Salvataggio finale
        orario_fine = datetime.now(ZoneInfo("Europe/Rome")).strftime('%d-%m-%Y %H:%M:%S')
        c.execute(
            "UPDATE tasks SET status = 'completed', blue_team_result = ?, completed_at = ? WHERE id = ?",
            (blue_team_response, orario_fine, task_id)
        )
        print(f"[+] Task #{task_id} COMPLETATO con successo via {backend}!")

    except Exception as e:
        print(f"[-] Errore critico nel Task #{task_id}: {str(e)}")
        c.execute(
            "UPDATE tasks SET status = 'error', blue_team_result = ? WHERE id = ?",
            (f"Errore di sistema o Filtro API: {str(e)}", task_id)
        )
    finally:
        conn.commit()
        conn.close()

    return True


if __name__ == '__main__':
    print("[*] Inizializzazione ANTARES Unified Worker...")

    print("[*] Worker in ascolto di nuovi task nel database...")

    while True:
        task_processed = process_pending_tasks()
        if not task_processed:
            time.sleep(5)
