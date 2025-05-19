from fastapi import FastAPI, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import yt_dlp
import requests
import json
import os
import pickle

app = FastAPI()

# Constants
TELEGRAM_BOT_TOKEN = '7643358360:AAEtlp6x4dSO_ea7NkBaIUozzeOo-z2Web4'
TELEGRAM_API_BASE = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}'
YOUTUBE_SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
TOKEN_PICKLE = 'token.pickle'
CLIENT_SECRETS_FILE = 'client_secret_892001422416-74a3m7taa8iqfp2ss8324bvq2m2nr601.apps.googleusercontent.com.json'

def send_telegram_message(chat_id: str, text: str):
    """Send a message back to Telegram user"""
    url = f'{TELEGRAM_API_BASE}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text
    }
    requests.post(url, json=payload)

def get_youtube_credentials():
    """Get or refresh YouTube API credentials"""
    creds = None
    if os.path.exists(TOKEN_PICKLE):
        with open(TOKEN_PICKLE, 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, YOUTUBE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PICKLE, 'wb') as token:
            pickle.dump(creds, token)
    
    return creds

def check_copyright(video_url: str) -> tuple[bool, str, str]:
    """Check video for potential copyright issues using yt-dlp"""
    ydl_opts = {
        'simulate': True,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return True, info.get('title', ''), info.get('description', '')
    except Exception as e:
        if 'copyright' in str(e).lower():
            return False, '', ''
        raise e

def download_video(video_url: str) -> str:
    """Download video using yt-dlp"""
    ydl_opts = {
        'format': 'best',
        'outtmpl': '%(title)s.%(ext)s'
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        return ydl.prepare_filename(info)

def upload_to_youtube(video_path: str, title: str, description: str) -> str:
    """Upload video to YouTube using YouTube Data API"""
    creds = get_youtube_credentials()
    youtube = build('youtube', 'v3', credentials=creds)
    
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': ['auto-upload']
        },
        'status': {
            'privacyStatus': 'private'
        }
    }
    
    insert_request = youtube.videos().insert(
        part=','.join(body.keys()),
        body=body,
        media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True)
    )
    
    response = insert_request.execute()
    return f'https://youtu.be/{response["id"]}'

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram webhook requests"""
    try:
        data = await request.json()
        message = data.get('message', {})
        chat_id = message.get('chat', {}).get('id')
        text = message.get('text', '')
        
        if not text or not chat_id:
            return {"status": "error", "message": "Invalid message format"}
        
        # Check if message contains a YouTube URL
        if 'youtube.com' not in text and 'youtu.be' not in text:
            send_telegram_message(chat_id, "Please send a valid YouTube video URL")
            return {"status": "error", "message": "Not a YouTube URL"}
        
        # Send initial status
        send_telegram_message(chat_id, "Processing your request...")
        
        # Check for copyright issues
        is_safe, title, description = check_copyright(text)
        if not is_safe:
            send_telegram_message(chat_id, "⚠️ This video might have copyright issues. Cannot proceed.")
            return {"status": "error", "message": "Copyright issues detected"}
        
        # Download the video
        send_telegram_message(chat_id, "✅ No copyright issues detected. Downloading video...")
        video_path = download_video(text)
        
        # Upload to YouTube
        send_telegram_message(chat_id, "📤 Uploading to YouTube...")
        youtube_url = upload_to_youtube(video_path, title, description)
        
        # Clean up downloaded file
        os.remove(video_path)
        
        # Send success message
        send_telegram_message(
            chat_id,
            f"✅ Upload complete!\nTitle: {title}\nYouTube URL: {youtube_url}"
        )
        
        return {"status": "success"}
        
    except Exception as e:
        if chat_id:
            send_telegram_message(chat_id, f"❌ Error: {str(e)}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
