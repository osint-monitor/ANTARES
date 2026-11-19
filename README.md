# ★ ANTARES
**Adversarial Narrative Threat Analysis and Response Evaluation System**

A cognitive simulation platform dedicated to national security and countering disinformation, engineered to run entirely on low-resource, CPU-only servers.
ANTARES allows analysts to practice adversarial simulation in a purely defensive context. By simulating how specific hostile actors (APTs, hacktivists, state-sponsored groups) manipulate news and narratives, defenders can proactively generate counter-narratives, debunking plans, and threat intelligence reports.

> 📖 **Read the full story:** discover the architecture, the challenges of running AI on a CPU-only server, and why I built ANTARES in my deep-dive article on [Medium](https://medium.com/@info.osintmonitor/building-antares-simulating-disinformation-campaigns-on-a-cpu-only-vps-3fe611e4f4b8?postPublishedType=repub.)

## ✨ Key Features

*   **Dual Analytical Engine:** Choose between **Google Gemini AI** (for complex reasoning via Cloud) or a **Local LLM via llama.cpp** (for absolute privacy and zero content restrictions).
*   **Low-Resource Optimization:** Specifically designed for budget VPS environments (e.g., 4 CPU cores, 8GB RAM, NO GPU) with hyper-optimized prompt engineering to prevent context window saturation on local models.
*   **Cultural Context Awareness:** Bilingual support (English/Italian) that structurally modifies AI behavior, tailoring prompts to the specific vulnerabilities and geopolitical contexts of the target population.
*   **Red Team vs. Blue Team Workflow:**
    *   *Red Team Phase:* Simulates the psychological objectives, target audiences, and social payloads of the attacker.
    *   *Blue Team Phase:* Generates an operational defense manual with counter-narratives and agency escalation directives.
*   **Multi-Actor Comparative Analysis:** Clone a task to compare how up to 4 different actors would manipulate the exact same piece of news. Export the comparative matrix as PDF or CSV.
*   **InfoSec Ready Exports:** Export analysis and IOCs in **STIX 2.1**, **MISP** (structured events for database correlation), or **PDF**.
*   **Semantic Threat Matching:** Automatically suggests the best hostile actor for a specific news piece based on semantic embeddings and historical tactics (mapped to DISARM frameworks).
*   **Structural Bilingual Support (ITA / ENG):** Beyond UI translation, language selection fundamentally changes AI behavior. Prompts are custom-tailored to target population dynamics, cultural vulnerabilities, and geopolitical contexts in both Italian and English.

## 🏗️ Architecture

To handle long-running AI tasks without blocking the UI, ANTARES uses an asynchronous architecture:
*   **Frontend/Backend:** Flask
*   **Task Queue:** SQLite database acting as a local queue.
*   **Background Worker:** A Python worker configured as a `systemd` service processes tasks sequentially (FIFO) to prevent CPU throttling.

## 🚀 Installation & Setup

### Prerequisites
*   Python 3.9+
*   At least 8GB of RAM (if using the local `llama.cpp` engine)
*   API Key for Google Gemini (if using the Cloud engine)

### 1. Clone the repository
```bash
git clone https://github.com/osint-monitor/ANTARES.git
cd ANTARES
```

### 2. Set up the virtual environment
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Environment Variables
Create a .env file in the root directory and configure your keys:
```bash
FLASK_SECRET_KEY="your_flask_key"
GEMINI_API_KEY="you_gemini_api_key"
```

### 4. Setup the Local LLM (Optional)
If you plan to use the local engine, download your preferred GGUF model (e.g., Llama-3-8B-Instruct.gguf) and place it in the models/ directory.

### 5. Run the Application
You need to start both the background worker and the web server.
For **local development**:
```bash
python worker_unified.py
python app.py
```

For **production deployment**, use Gunicorn behind a reverse proxy (Apache/Nginx) with systemd services, not the built-in Flask dev server.

### 🛡️ Demo Mode vs Admin Mode
By default, the platform can be exposed to the internet in Demo Mode (Read-Only).
In Demo Mode, visitors can explore telemetry dashboards, the multi-actor matrix, and the Threat Library, but the creation of new tasks is disabled to prevent resource abuse. To ingest new data, users must log in as Administrators.

### ⚠️ Responsible Use
ANTARES is a defensive research tool, not a disinformation generator. Every simulated attack (Red Team phase) is paired with a corresponding defensive countermeasure (Blue Team phase) by design. Threat actor profiles are built from publicly documented TTPs already mapped by MITRE ATT&CK and DISARM — the same sources used by CTI analysts worldwide.

If you fork or build on this code, please keep that defensive framing intact.

### 🤝 Contributing
Contributions are welcome! If you have ideas for new threat actor profiles, better prompts for the local LLM, or new export formats, feel free to open an Issue or submit a Pull Request.

### 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.
