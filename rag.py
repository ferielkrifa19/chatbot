
import chromadb
from chromadb.utils import embedding_functions
from pypdf import PdfReader

MODEL_NAME = "all-MiniLM-L6-v2"

embedding = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=MODEL_NAME
)

client = chromadb.PersistentClient(path="chroma_db")
NOM_COLLECTION = "documents"


def get_collection():
    return client.get_or_create_collection(
        name=NOM_COLLECTION,
        embedding_function=embedding,
    )


def lire_fichier(fichier):
    if fichier.name.lower().endswith(".pdf"):
        lecteur = PdfReader(fichier)
        texte = ""

        for page in lecteur.pages:
            texte += (page.extract_text() or "") + "\n"

        return texte

    return fichier.read().decode("utf-8", errors="ignore")


def decouper_texte(texte, taille=500):
    morceaux = []

    for i in range(0, len(texte), taille):
        morceau = texte[i:i + taille].strip()

        if morceau:
            morceaux.append(morceau)

    return morceaux


def ajouter_document(fichier):
    texte = lire_fichier(fichier)
    morceaux = decouper_texte(texte)

    if not morceaux:
        return 0

    collection = get_collection()

    ids = [f"{fichier.name}_{i}" for i in range(len(morceaux))]

    collection.upsert(
        ids=ids,
        documents=morceaux,
        metadatas=[{"source": fichier.name}] * len(morceaux),
    )

    return len(morceaux)


def chercher(question, n=3):
    collection = get_collection()

    if collection.count() == 0:
        return []

    resultats = collection.query(
        query_texts=[question],
        n_results=min(n, collection.count()),
    )

    return resultats["documents"][0]


def nombre_morceaux():
    return get_collection().count()


def supprimer_documents():
    try:
        client.delete_collection(name=NOM_COLLECTION)
    except Exception:
        pass
