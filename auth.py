
# auth.py

import sqlite3
import hashlib
import hmac
import secrets
import re
import streamlit as st

DB = "chat.db"


# ==========================================
# 1. CONNEXION À SQLITE
# ==========================================

def connexion_db():
    return sqlite3.connect(DB)


# ==========================================
# 2. CRÉER LA TABLE UTILISATEURS
# ==========================================

def initialiser_auth():
    with connexion_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS utilisateurs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                mot_de_passe TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


# ==========================================
# 3. HACHER LE MOT DE PASSE
# ==========================================

def hacher_mot_de_passe(mot_de_passe, sel=None):
    if sel is None:
        sel = secrets.token_hex(16)

    resultat = hashlib.pbkdf2_hmac(
        "sha256",
        mot_de_passe.encode("utf-8"),
        bytes.fromhex(sel),
        600000
    )

    return f"{sel}${resultat.hex()}"


def verifier_mot_de_passe(mot_de_passe, hash_stocke):
    try:
        sel, hash_original = hash_stocke.split("$", 1)
        hash_calcule = hacher_mot_de_passe(mot_de_passe, sel)
        return hmac.compare_digest(
            hash_calcule.split("$", 1)[1],
            hash_original
        )
    except (ValueError, TypeError):
        return False


# ==========================================
# 4. INSCRIPTION
# ==========================================

def inscrire(email, mot_de_passe):
    email = email.strip().lower()

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return False, "Adresse email invalide."

    if len(mot_de_passe) < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères."

    hash_mdp = hacher_mot_de_passe(mot_de_passe)

    try:
        with connexion_db() as conn:
            conn.execute("""
                INSERT INTO utilisateurs (email, mot_de_passe)
                VALUES (?, ?)
            """, (email, hash_mdp))

        return True, "Compte créé. Tu peux maintenant te connecter."

    except sqlite3.IntegrityError:
        return False, "Cette adresse email possède déjà un compte."


# ==========================================
# 5. CONNEXION
# ==========================================

def verifier_connexion(email, mot_de_passe):
    email = email.strip().lower()

    with connexion_db() as conn:
        utilisateur = conn.execute("""
            SELECT id, email, mot_de_passe
            FROM utilisateurs
            WHERE email = ?
        """, (email,)).fetchone()

    if utilisateur and verifier_mot_de_passe(
        mot_de_passe,
        utilisateur[2]
    ):
        return {
            "id": utilisateur[0],
            "email": utilisateur[1]
        }

    return None


# ==========================================
# 6. INTERFACE DE CONNEXION
# ==========================================

def afficher_auth():
    initialiser_auth()

    if "utilisateur" in st.session_state:
        return st.session_state.utilisateur

    st.title("🔐 Connexion au chatbot")
    st.write("Connecte-toi pour accéder à ton espace.")

    onglet_connexion, onglet_inscription = st.tabs([
        "Connexion",
        "Créer un compte"
    ])

    with onglet_connexion:
        with st.form("form_connexion"):
            email = st.text_input("Email", key="login_email")
            mot_de_passe = st.text_input(
                "Mot de passe",
                type="password",
                key="login_mdp"
            )

            envoyer = st.form_submit_button(
                "Se connecter",
                use_container_width=True
            )

        if envoyer:
            utilisateur = verifier_connexion(email, mot_de_passe)

            if utilisateur:
                st.session_state.utilisateur = utilisateur
                st.rerun()
            else:
                st.error("Email ou mot de passe incorrect.")

    with onglet_inscription:
        with st.form("form_inscription"):
            nouveau_email = st.text_input(
                "Email",
                key="register_email"
            )
            nouveau_mdp = st.text_input(
                "Mot de passe (8 caractères minimum)",
                type="password",
                key="register_mdp"
            )
            confirmation = st.text_input(
                "Confirmer le mot de passe",
                type="password",
                key="register_confirmation"
            )

            creer = st.form_submit_button(
                "Créer mon compte",
                use_container_width=True
            )

        if creer:
            if nouveau_mdp != confirmation:
                st.error("Les deux mots de passe ne correspondent pas.")
            else:
                ok, message = inscrire(nouveau_email, nouveau_mdp)

                if ok:
                    st.success(message)
                else:
                    st.error(message)

    return None


# ==========================================
# 7. DÉCONNEXION
# ==========================================

def deconnecter():
    st.session_state.pop("utilisateur", None)
    st.rerun()
