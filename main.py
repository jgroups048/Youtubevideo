from fastapi import FastAPI, Request
import httpx, os, json, subprocess
from pytube import YouTube
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GoogleRequest
import pickle

app = FastAPI()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"

@app.on_event("startup")
async def set_webhook():
    webhook_url = f"{os.getenv('RENDER_URL')}{WEBHOOK_PATH}"
    async with httpx.AsyncClient() as client:
        await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}")

@app.post(WEBHOOK_PATH)
async def telegram_webhook(req: Request):
    data = await req.json()
    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    if "youtube.com" in text or "youtu.be" in text:
        await send_message(chat_id, "Checking video for copyright...")
        if check_copyright_safe(text):
            await send_message(chat_id, "Downloading and uploading...")
            filepath = download_video(text)
            if filepath:
                upload_to_youtube(filepath)
                await send_message(chat_id, "Uploaded to your channel!")
            else:
                await send_message(chat_id, "Failed to download video.")
        else:
            await send_message(chat_id, "Video has copyright issues. Skipping upload.")
    else:
        await send_message(chat_id, "Please send a valid YouTube link.")
    return {"ok": True}

async def send_message(chat_id, text):
    async with httpx.AsyncClient() as client:
        await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text})

def check_copyright_safe(url):
    try:
        yt = YouTube(url)
        return not yt.age_restricted and "music" not in yt.title.lower()
    except:
        return False

def download_video(url):
    try:
        yt = YouTube(url)
        stream = yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc().first()
        return stream.download(filename="video.mp4")
    except Exception as e:
        print("Download error:", e)
        return None

def upload_to_youtube(filepath):
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None

    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("client_secrets.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    youtube = build("youtube", "v3", credentials=creds)
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": "Uploaded via Telegram Bot",
                "description": "This video was uploaded using a bot."
            },
            "status": {"privacyStatus": "private"}
        },
        media_body=filepath
    )
    response = request.execute()
    print("Uploaded:", response.get("id"))