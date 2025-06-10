import os
import chromadb
from openai import OpenAI
from dotenv import load_dotenv

# ✅ Cargar API key desde .env automáticamente
load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")


def inicializar_busqueda(api_key: str = None, persist_dir: str = "./chroma_faq_openai", collection_name: str = "faq_collection"):
    """
    Inicializa cliente de OpenAI y ChromaDB para consultas.
    """
    if api_key is None:
        api_key = API_KEY

    client = OpenAI(api_key=api_key)
    chroma_client = chromadb.PersistentClient(path=persist_dir)
    collection = chroma_client.get_collection(name=collection_name)

    return client, collection


def responder_pregunta(pregunta_usuario: str, openai_client, collection, k: int = 1) -> str:
    """
    Devuelve la respuesta más cercana a una pregunta usando embeddings.
    """
    try:
        print(f"🔍 Buscando respuesta para: {pregunta_usuario}")

        # Generar embedding
        embedding = openai_client.embeddings.create(
            input=pregunta_usuario,
            model="text-embedding-3-small"
        ).data[0].embedding

        print("🧠 Embedding generado correctamente.")

        # Buscar en la colección
        resultados = collection.query(
            query_embeddings=[embedding],
            n_results=k
        )

        pregunta_encontrada = resultados['documents'][0][0]
        respuesta = resultados['metadatas'][0][0].get("respuesta", "⚠️ No hay respuesta asociada.")

        print(f"🔹 Pregunta encontrada: {pregunta_encontrada}")
        print(f"📩 Respuesta encontrada: {respuesta}")

        return f"🤖 Pregunta similar encontrada:\n🔹 {pregunta_encontrada}\n\n📩 Respuesta:\n{respuesta}"

    except Exception as e:
        print(f"❌ Error en responder_pregunta: {e}")
        return f"❌ Error en la búsqueda: {e}"
