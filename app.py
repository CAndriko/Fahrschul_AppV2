import streamlit as st
import json
import os
import urllib.parse
from datetime import datetime
from openai import OpenAI

# -----------------------------------------------------------------------------
# 1. DATA MANAGEMENT
# -----------------------------------------------------------------------------
DATA_FILE = "student_data.json"

def load_data() -> dict:
    """Lädt die Schülerdatenbank. Gibt ein leeres Dictionary zurück, falls keine existiert."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    return {"students": {}}

def save_data(data: dict) -> None:
    """Speichert die Datenstruktur sicher in der JSON-Datei."""
    with open(DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)

def format_phone_number(phone: str) -> str:
    """Formatiert die eingegebene Telefonnummer passend für die WhatsApp-API."""
    cleaned = ''.join([c for c in phone if c.isdigit()])
    if not cleaned: return ""
    if cleaned.startswith("00"): cleaned = cleaned[2:]
    elif cleaned.startswith("0"): cleaned = "49" + cleaned[1:]
    return cleaned

def generate_export_text(student_name: str, logs: list) -> str:
    """Erstellt eine Textübersicht aller Fahrten für den Datei-Export."""
    text = f"FAHRSCHUL-AKTE: {student_name}\n" + "="*50 + "\n\n"
    for log in logs:
        text += f"Datum: {log['date']}\n" + "-"*50 + f"\nWhatsApp: {log['whatsapp_msg']}\n\nLogbuch:\n"
        for item in log.get('logbook', []):
            if isinstance(item, dict):
                text += f"{item.get('status', '')} {item.get('category', '')}: {item.get('note', '')}\n"
            else: text += f"- {str(item)}\n"
        text += "\n" + "="*50 + "\n\n"
    return text

# -----------------------------------------------------------------------------
# 2. AI LOGIC
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def analyze_driving_lesson(audio_bytes: bytes, student_name: str) -> dict:
    """Analysiert das aufgenommene Audio mit Whisper und wertet den Text mit gpt-4o-mini aus."""
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
        client = OpenAI(api_key=api_key)
        
        # Temporäre Audiodatei erstellen
        temp_file = "temp_recording.wav"
        with open(temp_file, "wb") as f: f.write(audio_bytes)
        
        # Transkription mit Whisper
        with open(temp_file, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
        
        # KI-Prompt mit strikter Trennung von WhatsApp (Du-Form) und internem Protokoll (3. Person)
        prompt = f"""
        Du bist ein professioneller Fahrlehrer-Assistent. Analysiere das Transkript der Fahrt von {student_name}.
        Transkript: '{transcript.text}'
        
        Erstelle ein JSON mit exakt dieser Struktur:
        {{
          "whatsapp_msg": "Ausführliche, herzliche Nachricht an den Schüler (in der 'Du'-Form) mit vielen Emojis. Erwähne JEDEN besprochenen Punkt im Detail.",
          "logbook": [
            {{ "status": "🟢", "category": "Thema", "note": "Ausführliche, sachliche Bewertung" }}
          ]
        }}
        
        WICHTIG FÜR DAS LOGBUCH:
        - Erstelle für JEDEN Aspekt einen eigenen Eintrag.
        - Die 'note' ist für die INTERNE Fahrschul-Akte (für den Chef/Prüfer). 
        - Schreibe in der 'note' ZWINGEND objektiv, sachlich und in der 3. Person (z.B. "Der Schüler hat...", "Gute Fahrzeugbeherrschung", NICHT "Du hast...").
        - Nutze NUR 🟢, 🟡, 🔴 als Status.
        - In 'note' keine Wortwiederholung der Kategorie.
        """
        
        # KI-Analyse
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={ "type": "json_object" },
            messages=[{"role": "system", "content": "Gründlicher Fahrlehrer-Assistent."}, {"role": "user", "content": prompt}]
        )
        
        if os.path.exists(temp_file): os.remove(temp_file)
        
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"whatsapp_msg": f"Fehler: {str(e)}", "logbook": []}

# -----------------------------------------------------------------------------
# 3. UI & DESIGN
# -----------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Logbuch Michael", page_icon="🚘", layout="centered")

    # CSS-Injektion für Design und Layout-Optimierung
    st.markdown("""
        <style>
        /* Blaue Primär-Buttons */
        div.stButton > button[kind="primary"] { background-color: #007bff !important; color: white !important; border: none !important; }
        div.stLinkButton > a { background-color: #007bff !important; color: white !important; border: none !important; }
        
        /* Reduziert den weißen Rand oben und unten im Hauptbereich */
        .block-container {
            padding-top: 2rem !important;
            padding-bottom: 1rem !important;
        }
        
        /* Reduziert den Abstand des Streamlit-Headers leicht, ohne das Menü zu verstecken */
        header {
            background-color: transparent !important;
        }
        </style>
    """, unsafe_allow_html=True)
    
    if "db" not in st.session_state: st.session_state.db = load_data()
    if "delete_confirm" not in st.session_state: st.session_state.delete_confirm = None

    # --- SIDEBAR ---
    with st.sidebar:
        st.title("🚘 Drive & Ride")
        st.subheader("Logbuch Michael")
        st.markdown("---")
        
        with st.expander("👤 Schüler hinzufügen"):
            with st.form("add_student_form", clear_on_submit=True):
                n_in = st.text_input("Name")
                p_in = st.text_input("Nummer")
                submitted = st.form_submit_button("Speichern", use_container_width=True)
                
                if submitted and n_in:
                    st.session_state.db["students"][n_in] = {"phone": format_phone_number(p_in), "logs": []}
                    save_data(st.session_state.db)
                    st.success("Gespeichert!")
                    st.rerun()

        s_list = list(st.session_state.db["students"].keys())
        selected_student = st.selectbox("📂 Aktiver Schüler", s_list) if s_list else None

        if selected_student:
            st.markdown("---")
            if st.session_state.delete_confirm != selected_student:
                if st.button("🗑️ Schüler löschen", use_container_width=True):
                    st.session_state.delete_confirm = selected_student; st.rerun()
            else:
                st.error(f"'{selected_student}' wirklich löschen?")
                c1, c2 = st.columns(2)
                if c1.button("Ja, weg damit", type="primary", use_container_width=True):
                    del st.session_state.db["students"][selected_student]
                    save_data(st.session_state.db); st.session_state.delete_confirm = None; st.rerun()
                if c2.button("Abbrechen", use_container_width=True):
                    st.session_state.delete_confirm = None; st.rerun()

    # --- MAIN AREA ---
    st.title("🎙️ Fahrstunde")
    if not selected_student:
        st.info("Wähle links einen Schüler aus.")
        return

    st.markdown(f"**Schüler:** {selected_student}")
    t1, t2 = st.tabs(["🎙️ Aufnahme", "🗂️ Archiv"])

    with t1:
        audio = st.audio_input("Hier sprechen")
        if audio:
            with st.spinner("Analyse läuft..."):
                res = analyze_driving_lesson(audio.getvalue(), selected_student)
                
                st.markdown("### 📱 WhatsApp Vorschau")
                st.info(res.get("whatsapp_msg", ""))
                
                phone = st.session_state.db["students"][selected_student].get("phone", "")
                if phone:
                    msg_encoded = urllib.parse.quote(res.get("whatsapp_msg", ""))
                    st.link_button("In WhatsApp senden", f"https://wa.me/{phone}?text={msg_encoded}", type="primary", use_container_width=True)
                
                st.markdown("---")
                st.markdown("### 🚦 Internes Ampel-Logbuch")
                h1, h2, h3 = st.columns([1, 2, 5])
                h1.write("**Status**"); h2.write("**Thema**"); h3.write("**Bewertung**")
                st.markdown("---")
                
                for item in res.get("logbook", []):
                    c1, c2, c3 = st.columns([1, 2, 5])
                    if isinstance(item, dict):
                        c1.markdown(f"### {item.get('status', '🟢')}")
                        c2.markdown(f"**{item.get('category', 'Info')}**")
                        c3.write(item.get('note', ''))
                    else: c2.write(str(item))
                
                st.markdown("---")
                if st.button("💾 In die Akte speichern", type="primary", use_container_width=True):
                    log = {"date": datetime.now().strftime("%d.%m.%Y, %H:%M"), "whatsapp_msg": res.get("whatsapp_msg", ""), "logbook": res.get("logbook", [])}
                    st.session_state.db["students"][selected_student]["logs"].insert(0, log)
                    save_data(st.session_state.db); st.success("Gespeichert!")

    with t2:
        logs = st.session_state.db["students"][selected_student].get("logs", [])
        if logs:
            st.download_button("📄 Akte exportieren", generate_export_text(selected_student, logs), file_name=f"{selected_student}.txt", use_container_width=True)
            for l in logs:
                with st.expander(f"📅 Fahrt am {l['date']}"):
                    st.write(l.get("whatsapp_msg", ""))
                    for i in l.get("logbook", []):
                        if isinstance(i, dict):
                            st.markdown(f"{i.get('status')} **{i.get('category')}**: {i.get('note')}")
        else: st.info("Leer.")

if __name__ == "__main__":
    main()