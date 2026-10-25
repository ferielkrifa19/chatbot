
import os
import sqlite3
import base64
import tempfile

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

import auth
import rag


# ==================================================
# CONFIGURATION
# ==================================================

load_dotenv()

st.set_page_config(
    page_title="Mon Chatbot IA",
    page_icon="🤖",
    layout="wide",
)

DB = "chat.db"
MODELE_WHISPER = "whisper-large-v3-turbo"

MODELES = [
    "qwen/qwen3.8-27b",
    "qwen/qwen3.6-27b",
]

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    st.error(
        "La clé GROQ_API_KEY est absente du fichier .env."
    )
    st.stop()

client = OpenAI(
    api_key=api_key,
    base_url="https://api.groq.com/openai/v1",
)


# ==================================================
# BASE DE DONNEES
# ==================================================

def requete(sql, params=(), fetch=False):
    """Exécute une requête SQLite et ferme la connexion."""
    conn = sqlite3.connect(DB)

    try:
        cur = conn.execute(sql, params)

        if fetch:
            resultat = cur.fetchall()
        else:
            resultat = cur.lastrowid

        conn.commit()
        return resultat

    finally:
        conn.close()


def initialiser_db():
    """Crée les tables nécessaires et adapte le schéma existant."""

    conn = sqlite3.connect(DB)

    try:
        cur = conn.cursor()

        # Création si la table n'existe pas encore.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titre TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER
            )
        """)

        # Migration automatique de l'ancienne table.
        cur.execute("PRAGMA table_info(conversations)")
        colonnes = [
            colonne[1] for colonne in cur.fetchall()
        ]

        if "user_id" not in colonnes:
            cur.execute("""
                ALTER TABLE conversations
                ADD COLUMN user_id INTEGER
            """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()

    finally:
        conn.close()


initialiser_db()


# ==================================================
# AUTHENTIFICATION
# ==================================================

# Cette fonction provient de ton fichier auth.py.
utilisateur = auth.afficher_auth()

if utilisateur is None:
    st.stop()

USER_ID = int(utilisateur["id"])


# ==================================================
# GESTION DES CONVERSATIONS
# ==================================================

def creer_conversation(titre, user_id):
    return requete(
        """
        INSERT INTO conversations (titre, user_id)
        VALUES (?, ?)
        """,
        (titre, user_id),
    )


def lister_conversations(user_id):
    return requete(
        """
        SELECT id, titre, created_at
        FROM conversations
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,),
        fetch=True,
    )


def conversation_autorisee(conv_id, user_id):
    resultat = requete(
        """
        SELECT id
        FROM conversations
        WHERE id = ? AND user_id = ?
        """,
        (conv_id, user_id),
        fetch=True,
    )

    return bool(resultat)


def charger_messages(conv_id, user_id):
    if not conversation_autorisee(conv_id, user_id):
        return []

    return requete(
        """
        SELECT role, content
        FROM messages
        WHERE conversation_id = ?
        ORDER BY id ASC
        """,
        (conv_id,),
        fetch=True,
    )


def ajouter_message(conv_id, user_id, role, content):
    if not conversation_autorisee(conv_id, user_id):
        raise PermissionError(
            "Cette conversation ne vous appartient pas."
        )

    requete(
        """
        INSERT INTO messages (conversation_id, role, content)
        VALUES (?, ?, ?)
        """,
        (conv_id, role, content),
    )


def supprimer_conversation(conv_id, user_id):
    if not conversation_autorisee(conv_id, user_id):
        return

    requete(
        "DELETE FROM messages WHERE conversation_id = ?",
        (conv_id,),
    )

    requete(
        """
        DELETE FROM conversations
        WHERE id = ? AND user_id = ?
        """,
        (conv_id, user_id),
    )


# ==================================================
# TRANSCRIPTION VOCALE
# ==================================================

def transcrire(audio):
    """Convertit un enregistrement vocal en texte français."""

    resultat = client.audio.transcriptions.create(
        file=(
            audio.name or "voix.wav",
            audio.getvalue(),
            audio.type or "audio/wav",
        ),
        model=MODELE_WHISPER,
        language="fr",
        response_format="text",
    )

    if isinstance(resultat, str):
        return resultat.strip()

    return resultat.text.strip()


# ==================================================
# SESSION STREAMLIT
# ==================================================

if "conv_id" not in st.session_state:
    st.session_state.conv_id = None

if "audio_key" not in st.session_state:
    st.session_state.audio_key = 0

if "img_key" not in st.session_state:
    st.session_state.img_key = 0


# ==================================================
# BARRE LATERALE
# ==================================================

with st.sidebar:
    st.title("🤖 Mon Chatbot")

    st.write("Connecté avec :")
    st.write(utilisateur["email"])

    if st.button("Déconnexion", use_container_width=True):
        auth.deconnecter()
        st.rerun()

    st.divider()

    if st.button("➕ Nouvelle conversation",
                 use_container_width=True):
        st.session_state.conv_id = None
        st.rerun()

    st.subheader("Paramètres du modèle")

    modele = st.selectbox(
        "Modèle IA",
        MODELES,
        index=0,
    )

    temperature = st.slider(
        "Température",
        min_value=0.0,
        max_value=2.0,
        value=0.7,
        step=0.1,
        help=(
            "Une valeur basse favorise des réponses plus "
            "prévisibles. Une valeur élevée peut les rendre "
            "plus variées."
        ),
    )

    consigne = st.text_area(
        "Consigne système",
        value=(
            "Tu es un assistant utile. "
            "Réponds en français de manière claire et précise."
        ),
        height=120,
    )

    st.divider()

    # ----------------------------------------------
    # DOCUMENTS RAG
    # ----------------------------------------------

    st.subheader("📚 Documents (RAG)")

    utiliser_rag = st.checkbox(
        "Utiliser mes documents",
        value=False,
    )

    fichiers = st.file_uploader(
        "Importer un PDF ou un fichier TXT",
        type=["pdf", "txt"],
        accept_multiple_files=True,
    )

    if st.button("Indexer les documents",
                 use_container_width=True):

        if not fichiers:
            st.warning("Choisis au moins un fichier.")

        else:
            succes = 0

            for fichier in fichiers:
                chemin_temporaire = None

                try:
                    suffixe = os.path.splitext(
                        fichier.name
                    )[1].lower()

                    with tempfile.NamedTemporaryFile(
                        delete=False,
                        suffix=suffixe,
                    ) as temp:
                        temp.write(fichier.getvalue())
                        chemin_temporaire = temp.name

                    # Signature connue de ton module rag.py.
                    rag.ajouter_document(chemin_temporaire)

                    succes += 1

                except Exception as erreur:
                    st.error(
                        f"Erreur avec {fichier.name} : {erreur}"
                    )

                finally:
                    if (
                        chemin_temporaire
                        and os.path.exists(chemin_temporaire)
                    ):
                        os.remove(chemin_temporaire)

            if succes:
                st.success(
                    f"{succes} fichier(s) traité(s)."
                )

    try:
        st.caption(
            f"Nombre de morceaux indexés : "
            f"{rag.nombre_morceaux()}"
        )
    except Exception:
        st.caption(
            "Le nombre de morceaux n'est pas disponible."
        )

    if st.button("Effacer les documents indexés",
                 use_container_width=True):

        try:
            rag.supprimer_documents()
            st.success("Documents indexés supprimés.")
        except Exception as erreur:
            st.error(f"Erreur : {erreur}")

    st.divider()

    # ----------------------------------------------
    # IMAGE
    # ----------------------------------------------

    st.subheader("🖼️ Image")

    image_fichier = st.file_uploader(
        "Joindre une image à votre question",
        type=["png", "jpg", "jpeg", "webp"],
        key=f"image_{st.session_state.img_key}",
    )

    st.divider()

    # ----------------------------------------------
    # HISTORIQUE
    # ----------------------------------------------

    st.subheader("Historique")

    conversations = lister_conversations(USER_ID)

    if not conversations:
        st.caption("Aucune conversation pour le moment.")

    for conv in conversations:
        conv_id, titre, date_creation = conv

        col1, col2 = st.columns([4, 1])

        with col1:
            if st.button(
                titre[:35],
                key=f"ouvrir_{conv_id}",
                use_container_width=True,
            ):
                st.session_state.conv_id = conv_id
                st.rerun()

        with col2:
            if st.button(
                "🗑️",
                key=f"supprimer_{conv_id}",
            ):
                supprimer_conversation(
                    conv_id,
                    USER_ID,
                )

                if st.session_state.conv_id == conv_id:
                    st.session_state.conv_id = None

                st.rerun()


# ==================================================
# AFFICHAGE DE LA CONVERSATION
# ==================================================

st.title("Chatbot IA")

conv_id = st.session_state.conv_id

if conv_id is not None:
    if not conversation_autorisee(conv_id, USER_ID):
        st.session_state.conv_id = None
        st.rerun()

    historique = charger_messages(conv_id, USER_ID)

    for role, contenu in historique:
        with st.chat_message(role):
            st.markdown(contenu)


# ==================================================
# ENTREE VOCALE ET TEXTUELLE
# ==================================================

st.subheader("🎙️ Poser une question à voix haute")

audio = st.audio_input(
    "Parle, puis arrête l'enregistrement",
    key=f"audio_{st.session_state.audio_key}",
)

question_texte = st.chat_input(
    "Écris ta question ici..."
)

question = None

# Une question écrite est prioritaire.
if question_texte and question_texte.strip():
    question = question_texte.strip()

elif audio is not None:
    with st.spinner("Transcription de l'enregistrement..."):
        try:
            question = transcrire(audio)

            if question:
                st.info(f"Question transcrite : {question}")
            else:
                st.warning(
                    "Aucune parole n'a été détectée."
                )

        except Exception as erreur:
            st.error(
                f"Impossible de transcrire l'audio : {erreur}"
            )


# ==================================================
# TRAITEMENT DE LA QUESTION
# ==================================================

if question:

    # Créer une conversation si nécessaire.
    conv_id = st.session_state.conv_id

    if conv_id is None:
        titre = question[:50]

        conv_id = creer_conversation(
            titre,
            USER_ID,
        )

        st.session_state.conv_id = conv_id

    # Vérification supplémentaire d'accès.
    if not conversation_autorisee(conv_id, USER_ID):
        st.error("Accès à cette conversation refusé.")
        st.stop()

    # Préparer le contexte RAG.
    contexte_rag = ""

    if utiliser_rag:
        try:
            resultats = rag.chercher(question, n=3)

            if resultats:
                # Prend en charge des résultats textuels
                # ainsi que des documents renvoyés sous forme
                # de dictionnaires.
                textes = []

                for element in resultats:
                    if isinstance(element, str):
                        textes.append(element)

                    elif isinstance(element, dict):
                        texte = (
                            element.get("texte")
                            or element.get("text")
                            or element.get("content")
                            or element.get("document")
                        )

                        if texte:
                            textes.append(str(texte))

                    else:
                        textes.append(str(element))

                if textes:
                    contexte_rag = "\n\n".join(textes)

        except Exception as erreur:
            st.error(f"Erreur RAG : {erreur}")

    # Construire le message système.
    systeme = consigne.strip()

    if contexte_rag:
        systeme += (
            "\n\nUtilise les extraits suivants pour répondre "
            "à la question lorsque cela est pertinent. "
            "Si les extraits ne contiennent pas la réponse, "
            "indique-le clairement.\n\n"
            "EXTRAITS DES DOCUMENTS :\n"
            + contexte_rag
        )

    messages = [
        {
            "role": "system",
            "content": systeme,
        }
    ]

    # Charger l'historique de cette conversation.
    historique = charger_messages(
        conv_id,
        USER_ID,
    )

    for role, contenu in historique:
        messages.append({
            "role": role,
            "content": contenu,
        })

    # Ajouter l'image si l'utilisateur en a fourni une.
    contenu_question = question

    if image_fichier is not None:
        image_bytes = image_fichier.getvalue()
        image_base64 = base64.b64encode(
            image_bytes
        ).decode("utf-8")

        type_image = (
            image_fichier.type or "image/png"
        )

        contenu_question = [
            {
                "type": "text",
                "text": question,
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{type_image};base64,"
                        f"{image_base64}"
                    )
                },
            },
        ]

    # Enregistrer la question.
    ajouter_message(
        conv_id,
        USER_ID,
        "user",
        question,
    )

    # Afficher la question dans l'interface.
    with st.chat_message("user"):
        st.markdown(question)

        if image_fichier is not None:
            st.image(
                image_fichier,
                caption="Image jointe",
                use_container_width=True,
            )

    messages.append({
        "role": "user",
        "content": contenu_question,
    })

    # Générer la réponse du modèle.
    with st.chat_message("assistant"):
        with st.spinner("Le chatbot réfléchit..."):

            try:
                reponse = client.chat.completions.create(
                    model=modele,
                    messages=messages,
                    temperature=temperature,
                )

                texte_reponse = (
                    reponse.choices[0].message.content
                )

                if not texte_reponse:
                    texte_reponse = (
                        "Le modèle n'a pas retourné de texte."
                    )

                st.markdown(texte_reponse)

                ajouter_message(
                    conv_id,
                    USER_ID,
                    "assistant",
                    texte_reponse,
                )

                if contexte_rag:
                    with st.expander(
                        "Voir le contexte documentaire utilisé"
                    ):
                        st.write(contexte_rag)

            except Exception as erreur:
                st.error(
                    f"Erreur lors de la génération : {erreur}"
                )

    # Réinitialiser les champs audio et image.
    st.session_state.audio_key += 1
    st.session_state.img_key += 1

    st.rerun()
