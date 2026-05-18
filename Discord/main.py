import logging
import os
from typing import Any
import discord
import requests
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
DEFAULT_JARVIS_API_URL = "http://127.0.0.1:8001/api/chat"
JARVIS_API_URL = os.getenv("JARVIS_API_URL", DEFAULT_JARVIS_API_URL).strip() or DEFAULT_JARVIS_API_URL
JARVIS_API_TIMEOUT = float(os.getenv("JARVIS_API_TIMEOUT", "180").strip() or "180")
MAX_HISTORY = 20

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jarvis-discord")


def validate_jarvis_api_url(url: str) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        raise RuntimeError("JARVIS_API_URL est vide. Configure un endpoint comme http://127.0.0.1:8001/api/chat")

    if not cleaned.startswith(("http://", "https://")):
        raise RuntimeError(
            "JARVIS_API_URL invalide: il manque le schema http:// ou https:// "
            f"(valeur actuelle: {cleaned})"
        )

    low = cleaned.lower().rstrip("/")
    if low in {"http://localhost:11434", "http://127.0.0.1:11434", "https://localhost:11434", "https://127.0.0.1:11434"}:
        raise RuntimeError(
            "JARVIS_API_URL pointe vers Ollama (port 11434). "
            "Il faut l'URL de l'API Jarvis, par exemple: http://127.0.0.1:8001/api/chat"
        )

    return cleaned


def get_status_url(chat_url: str) -> str:
    if "/api/chat" in chat_url:
        return chat_url.replace("/api/chat", "/api/status")
    return chat_url.rstrip("/") + "/api/status"


def get_google_connect_url(chat_url: str) -> str:
    if "/api/chat" in chat_url:
        return chat_url.replace("/api/chat", "/api/google/connect")
    return chat_url.rstrip("/") + "/api/google/connect"


intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
conversations: dict[int, list[dict[str, str]]] = {}
JARVIS_API_URL = validate_jarvis_api_url(JARVIS_API_URL)


def trim_history(history: list[dict[str, str]]) -> None:
    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]


def normalize_api_reply(reply: str) -> str:
    cleaned = (reply or "").strip()
    lowered = cleaned.lower()

    if "compte google non configuré" in lowered or "variables manquantes: google_token_file" in lowered:
        return "Google pas connecte. Veuillez faire la connexion avec la commande /google."

    return cleaned


def ask_jarvis(history: list[dict[str, str]], message: str) -> str:
    payload: dict[str, Any] = {
        "message": message,
        "history": history,
        "temperature": 0.3,
    }
    response = requests.post(JARVIS_API_URL, json=payload, timeout=JARVIS_API_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or "reply" not in data:
        raise RuntimeError(
            "Réponse API invalide (champ 'reply' absent). "
            "Vérifie que JARVIS_API_URL pointe vers /api/chat de Jarvis."
        )
    raw_reply = (data.get("reply") or "Je n'ai pas de réponse pour le moment.")
    return normalize_api_reply(raw_reply)


async def send_long_message(channel: discord.abc.Messageable, text: str) -> None:
    if not text:
        return
    for i in range(0, len(text), 2000):
        await channel.send(text[i : i + 2000])


@client.event
async def on_ready() -> None:
    await tree.sync()
    logger.info("Jarvis est pret: %s", client.user)
    logger.info("Endpoint API Jarvis: %s", JARVIS_API_URL)


@tree.command(name="jarvis_status", description="Problème de connexion entre Discord et l'API Jarvis")
async def jarvis_status(interaction: discord.Interaction) -> None:
    try:
        status_url = get_status_url(JARVIS_API_URL)
        response = requests.get(status_url, timeout=5)
        response.raise_for_status()
        data = response.json()
        model = data.get("model_name", "inconnu")
        online = data.get("model_online", False)
        await interaction.response.send_message(
            f"Jarvis API connectee. Modele: `{model}` | online: `{online}`"
        )
    except Exception as exc:
        await interaction.response.send_message(
            f"Impossible de joindre Jarvis API: `{exc}`",
            ephemeral=True,
        )


@tree.command(name="google", description="Connecter Google pour les actions mail et calendrier")
async def google_connect(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        connect_url = get_google_connect_url(JARVIS_API_URL)
        response = requests.post(connect_url, timeout=JARVIS_API_TIMEOUT)
        if response.status_code >= 400:
            try:
                details = response.json().get("detail")
            except Exception:
                details = response.text.strip()
            raise RuntimeError(details or f"HTTP {response.status_code}")

        data = response.json() if response.content else {}
        token_path = "(inconnu)"
        message = "Compte Google connecte."
        if isinstance(data, dict):
            token_path = str(data.get("token_path") or token_path)
            message = str(data.get("message") or message)

        await interaction.followup.send(
            (
                f"{message}\n"
                f"Token OAuth cree: `{token_path}`\n"
                "Si une page de consentement Google s'ouvre, valide-la pour terminer la connexion."
            ),
            ephemeral=True,
        )
    except Exception as exc:
        await interaction.followup.send(
            f"Connexion Google impossible: `{exc}`",
            ephemeral=True,
        )


@tree.command(name="description", description="Afficher ce que Jarvis peut faire")
async def description(interaction: discord.Interaction) -> None:
    try:
        reply = ask_jarvis([], "que peux tu faire")
        await interaction.response.send_message(reply)
    except Exception as exc:
        await interaction.response.send_message(
            f"Impossible de recuperer la description: `{exc}`",
            ephemeral=True,
        )


@client.event
async def on_message(message: discord.Message) -> None:
    
    if message.author.bot:
        return
    if message.content.startswith("/"):
        return
    if not client.user:
        return

    mentioned = client.user in message.mentions
    if not mentioned:
        return

    cleaned_content = message.content
    cleaned_content = cleaned_content.replace(f"<@{client.user.id}>", "")
    cleaned_content = cleaned_content.replace(f"<@!{client.user.id}>", "")
    cleaned_content = cleaned_content.strip()
    if not cleaned_content:
        await message.channel.send("Mentionne-moi avec un message, par exemple: @Jarvis Bonjour !")
        return

    history = conversations.setdefault(message.author.id, [])
    history.append({"role": "user", "content": cleaned_content})
    trim_history(history)

    try:
        reply = ask_jarvis(history, cleaned_content)
    except Exception as exc:
        logger.exception("Erreur avec l'API Jarvis")
        reply = f"Erreur avec l'API Jarvis: {exc}"

    history.append({"role": "assistant", "content": reply})
    trim_history(history)
    await send_long_message(message.channel, reply)


if not DISCORD_TOKEN:
    raise RuntimeError("Le token est manquant dans le fichier .env")

client.run(DISCORD_TOKEN)