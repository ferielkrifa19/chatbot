
import os
import sqlite3
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

st.set_page_config(page_title="Mon chatbot", page_icon="🤖", layout="wide")

DB = "chat.db"

def requete(sql, params=(), fetch=False):
    with sqlite3.connect(DB) as conn:
        cur = conn.execute(sql, params)
        if fetch:
            return cur.fetchall()
        return cur.lastrowid

def init_db():
    requete("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titre TEXT NOT NULL
        )
    """)
    requete("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER,
            role TEXT,
            content TEXT
        )
    """)

def creer_conversation(titre):
    return requete(
        "INSERT INTO conversations (titre) VALUES (?)",
        (titre,)
    )

def lister_conversations():
    return requete(
        "SELECT id, titre FROM conversations ORDER BY id DESC",
        fetch=True
    )

def charger_messages(conv_id):
    lignes = requete(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id",
        (conv_id,),
        fetch=True
    )
    return [{"role": role, "content": content} for role, content in lignes]

def ajouter_message(conv_id, role, content):
    requete(
        "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
        (conv_id, role, content)
    )

def supprimer_conversation(conv_id):
    requete("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
    requete("DELETE FROM conversations WHERE id = ?", (conv_id,))

init_db()

if "conv_id" not in st.session_state:
    st.session_state.conv_id = None

with st.sidebar:
    st.header("⚙️ Paramètres")
    modele = st.selectbox("Modèle", ["openai/gpt-oss-120b"])
    temperature = st.slider("Créativité", 0.0, 1.0, 0.7, 0.1)
    consigne = st.text_area(
        "Consigne du bot",
        "Tu es un assistant sympa qui répond en français."
    )

    st.divider()
    st.header("💬 Conversations")

    if st.button("➕ Nouvelle conversation", use_container_width=True):
        st.session_state.conv_id = None
        st.rerun()

    for cid, titre in lister_conversations():
        col1, col2 = st.columns([4, 1])

        if col1.button(titre, key=f"ouvrir_{cid}", use_container_width=True):
            st.session_state.conv_id = cid
            st.rerun()

        if col2.button("🗑️", key=f"supprimer_{cid}"):
            supprimer_conversation(cid)
            if st.session_state.conv_id == cid:
                st.session_state.conv_id = None
            st.rerun()

st.title("🤖 Mon chatbot")

if st.session_state.conv_id is not None:
    historique = charger_messages(st.session_state.conv_id)
    for message in historique:
        with st.chat_message(message["role"]):
            st.write(message["content"])

question = st.chat_input("Écris ta question ici...")

if question:
    nouvelle = st.session_state.conv_id is None

    if nouvelle:
        st.session_state.conv_id = creer_conversation(question[:30])

    conv_id = st.session_state.conv_id

    ajouter_message(conv_id, "user", question)

    with st.chat_message("user"):
        st.write(question)

    try:
        cle = os.getenv("GROQ_API_KEY")

        if not cle:
            st.error("La clé GROQ_API_KEY est absente du fichier .env.")
            st.stop()

        client = OpenAI(
            api_key=cle,
            base_url="https://api.groq.com/openai/v1"
        )

        messages = [
            {"role": "system", "content": consigne}
        ] + charger_messages(conv_id)

        with st.chat_message("assistant"):
            reponse = client.chat.completions.create(
                model=modele,
                messages=messages,
                temperature=temperature
            ).choices[0].message.content

            st.write(reponse)

        ajouter_message(conv_id, "assistant", reponse)

    except Exception as e:
        st.error(f"Une erreur est survenue : {e}")

    if nouvelle:
        st.rerun()
