import streamlit as st
import json
import os
import urllib.parse
from datetime import datetime
import requests
from openai import OpenAI

# -----------------------------------------------------------------------------
# 1. DATABASE MANAGEMENT (SUPABASE via REST API)
# -----------------------------------------------------------------------------
def get_supabase_headers() -> dict:
    key = st.secrets["SUPABASE_KEY"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

def get_supabase_url() -> str:
    return f"{st.secrets['SUPABASE_URL']}/rest/v1/students"

def load_data() -> dict:
    url = get_supabase_url()
    headers = get_supabase_headers()
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        db_data = {"students": {}}
        for row in data:
            db_data["students"][row["name"]] = {
                "phone": row.get("phone", ""),
                "logs": row.get("logs", [])
            }
        return db_data
    except Exception:
        return {"students": {}}

def save_student(name: str, phone: str, logs: list) -> bool:
    url = f"{get_supabase_url()}?on_conflict=name"
    headers = get_supabase_headers()
    headers["Prefer"] = "resolution=merge-duplicates"
    
    payload = {
        "name": name,
        "phone": phone,
        "logs": logs
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        err_msg = response.text if 'response' in locals() else str(e)
        st.error(f"Cloud-Fehler beim Speichern: {err_msg}")
        return False

def delete_student_from_db(name: str) -> bool:
    url = f"{get_supabase_url()}?name=eq.{urllib.parse.quote(name)}"
    headers = get_supabase_headers()
    
    try:
        response = requests.delete(url, headers=headers)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        err_msg = response.text if 'response' in locals() else str(e)
        st.error(f"Cloud-Fehler beim Löschen: {err_msg}")
        return False

def format_phone_number(phone: str) -> str:
    cleaned = ''.join([c for c in phone if c.isdigit()])
    if not cleaned: return ""
    if cleaned.startswith("00"): cleaned = cleaned[2:]
    elif cleaned.startswith("0"): cleaned = "49" + cleaned[1:]
    return cleaned

def generate_export_text(student_name: str, logs: list) -> str:
    export_text = f"FAHRSCHUL-AKTE: {student_name}\n" + "="*50 + "\n\n"
    for log in logs:
        export_text += f"Datum: {log['date']}\n" + "-"*50 + f"\nWhatsApp: {log['whatsapp_msg']}\n\nLogbuch:\n"
        for item in log.get('logbook', []):
            if isinstance(item, dict):
                export_text += f"{item.get('status', '')} {item.get('category', '')}: {item.get('note', '')}\n"
            else: 
                export_text += f"- {str(item)}\n"
        export_text += "\n" + "="*50 + "\n\n"
    return export_text

# -----------------------------------------------------------------------------
# 2. AI LOGIC
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def analyze_driving_lesson(audio_bytes: bytes, student_name: str) -> dict:
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
        client = OpenAI(api_key=api_key)
        
        temp_file = "temp_recording.wav"
        with open(temp_file, "wb") as f: 
            f.write(audio_bytes)
        
        with open(temp_file, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
        
        system_prompt = f"""
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
        - Die 'note' ist für die INTERNE Fahrschul-Akte. 
        - Schreibe in der 'note' ZWINGEND objektiv, sachlich und in der 3. Person.
        - Nutze NUR 🟢, 🟡, 🔴 als Status.
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": "Gründlicher Fahrlehrer-Assistent."}, 
                {"role": "user", "content": system_prompt}
            ]
        )
        
        if os.path.exists(temp_file): 
            os.remove(temp_file)
        
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"whatsapp_msg": f"Fehler: {str(e)}", "logbook": []}

# -----------------------------------------------------------------------------
# 3. UI & DESIGN
# -----------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Logbuch Michael", page_icon="🚘", layout="centered")

    st.markdown("""
        <style>
        div.stButton > button[kind="primary"] { background-color: #007bff !important; color: white !important; border: none !important; }
        div.stLinkButton > a { background-color: #007bff !important; color: white !important; border: none !important; }
        footer {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)
    
    if "delete_confirm" not in st.session_state: st.session_state.delete_confirm = None
    if "audio_key" not in st.session_state: st.session_state.audio_key = 0
    if "active_student" not in st.session_state: st.session_state.active_student = None

    db_data = load_data()

    # --- SIDEBAR ---
    with st.sidebar:
        st.title("🚘 Drive & Ride")
        st.subheader("Logbuch Michael")
        st.markdown("---")
        
        if st.button("🏠 Startseite", type="primary", use_container_width=True):
            st.session_state.active_student = None
            st.rerun()
            
        st.markdown("---")
        
        with st.expander("👤 Schüler hinzufügen"):
            with st.form("add_student_form", clear_on_submit=True):
                name_input = st.text_input("Name")
                phone_input = st.text_input("Nummer")
                submitted = st.form_submit_button("Speichern", use_container_width=True)
                
                if submitted and name_input:
                    formatted_phone = format_phone_number(phone_input)
                    if save_student(name_input, formatted_phone, []):
                        st.success("Gespeichert!")
                        st.rerun()

        student_list = list(db_data["students"].keys())
        options = ["-- Schüler wählen --"] + student_list
        
        current_index = 0
        if st.session_state.active_student in student_list:
            current_index = student_list.index(st.session_state.active_student) + 1
            
        selected_option = st.selectbox("📂 Meine Schüler", options, index=current_index)
        
        if selected_option != "-- Schüler wählen --" and selected_option != st.session_state.active_student:
            st.session_state.active_student = selected_option
            st.rerun()
        elif selected_option == "-- Schüler wählen --" and st.session_state.active_student is not None:
            st.session_state.active_student = None
            st.rerun()

        active_student = st.session_state.active_student

        if active_student:
            st.markdown("---")
            if st.session_state.delete_confirm != active_student:
                if st.button("🗑️ Schüler löschen", use_container_width=True):
                    st.session_state.delete_confirm = active_student
                    st.rerun()
            else:
                st.error(f"'{active_student}' wirklich löschen?")
                col1, col2 = st.columns(2)
                if col1.button("Ja, weg damit", type="primary", use_container_width=True):
                    if delete_student_from_db(active_student):
                        st.session_state.active_student = None
                        st.session_state.delete_confirm = None
                        st.rerun()
                if col2.button("Abbrechen", use_container_width=True):
                    st.session_state.delete_confirm = None
                    st.rerun()

    # --- MAIN AREA ---
    if not active_student:
        st.title("👋 Willkommen, Michael")
        st.markdown("Wähle links einen Schüler aus der Liste oder füge einen neuen hinzu, um die nächste Fahrstunde zu protokollieren.")
        st.markdown("---")
        
        total_students = len(db_data["students"])
        total_logs = sum(len(data.get("logs", [])) for data in db_data["students"].values())
        
        col1, col2 = st.columns(2)
        col1.metric("👥 Aktive Schüler", total_students)
        col2.metric("📝 Erfasste Fahrten", total_logs)
        return

    st.title(f"🎓 {active_student}")
    student_logs = db_data["students"][active_student].get("logs", [])
    student_phone = db_data["students"][active_student].get("phone", "")
    
    metric1, metric2, metric3 = st.columns(3)
    metric1.metric("🚗 Fahrten", len(student_logs))
    
    last_date = student_logs[0]["date"].split(",")[0] if student_logs else "-"
    metric2.metric("📅 Letzte Fahrt", last_date)
    
    with metric3:
        st.write("") 
        if student_phone:
            st.link_button("💬 WhatsApp öffnen", f"https://wa.me/{student_phone}", use_container_width=True)
            
    st.markdown("---")

    tab1, tab2 = st.tabs(["🎙️ Aufnahme", "🗂️ Archiv"])

    with tab1:
        audio_input = st.audio_input("Hier sprechen", key=f"audio_{st.session_state.audio_key}")
        
        if audio_input:
            with st.spinner("Analyse läuft..."):
                analysis_result = analyze_driving_lesson(audio_input.getvalue(), active_student)
                
                st.markdown("### 📱 WhatsApp Vorschau")
                st.info(analysis_result.get("whatsapp_msg", ""))
                
                if student_phone:
                    msg_encoded = urllib.parse.quote(analysis_result.get("whatsapp_msg", ""))
                    st.link_button("In WhatsApp senden", f"https://wa.me/{student_phone}?text={msg_encoded}", type="primary", use_container_width=True)
                
                st.markdown("---")
                st.markdown("### 🚦 Internes Ampel-Logbuch")
                header1, header2, header3 = st.columns([1, 2, 5])
                header1.write("**Status**")
                header2.write("**Thema**")
                header3.write("**Bewertung**")
                st.markdown("---")
                
                for item in analysis_result.get("logbook", []):
                    col1, col2, col3 = st.columns([1, 2, 5])
                    if isinstance(item, dict):
                        col1.markdown(f"### {item.get('status', '🟢')}")
                        col2.markdown(f"**{item.get('category', 'Info')}**")
                        col3.write(item.get('note', ''))
                    else: 
                        col2.write(str(item))
                
                st.markdown("---")
                if st.button("💾 In die Akte speichern & Abschließen", type="primary", use_container_width=True):
                    new_log_entry = {
                        "date": datetime.now().strftime("%d.%m.%Y, %H:%M"), 
                        "whatsapp_msg": analysis_result.get("whatsapp_msg", ""), 
                        "logbook": analysis_result.get("logbook", [])
                    }
                    student_logs.insert(0, new_log_entry)
                    if save_student(active_student, student_phone, student_logs):
                        st.session_state.audio_key += 1
                        st.rerun()

    with tab2:
        if student_logs:
            green_count = yellow_count = red_count = 0
            for log in student_logs:
                for item in log.get("logbook", []):
                    if isinstance(item, dict):
                        status = item.get("status", "")
                        if "🟢" in status: green_count += 1
                        elif "🟡" in status: yellow_count += 1
                        elif "🔴" in status: red_count += 1
            
            st.markdown("### 📊 Gesamte Ampel-Statistik")
            stat1, stat2, stat3 = st.columns(3)
            stat1.metric("🟢 Top", green_count)
            stat2.metric("🟡 Üben", yellow_count)
            stat3.metric("🔴 Kritisch", red_count)
            st.markdown("---")
            
            export_content = generate_export_text(active_student, student_logs)
            st.download_button("📄 Komplette Akte exportieren", export_content, file_name=f"{active_student}.txt", use_container_width=True)
            st.markdown("---")
            
            for log in student_logs:
                with st.expander(f"📅 Fahrt am {log['date']}"):
                    st.write(log.get("whatsapp_msg", ""))
                    for item in log.get("logbook", []):
                        if isinstance(item, dict):
                            st.markdown(f"{item.get('status')} **{item.get('category')}**: {item.get('note')}")
        else: 
            st.info("Noch keine Fahrten gespeichert.")

if __name__ == "__main__":
    main()