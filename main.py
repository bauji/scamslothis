import os
import time

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

load_dotenv()
app = FastAPI()

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/speech-to-text"


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    return {"ok": True}


async def transcribe(audio: UploadFile) -> str:
    data = await audio.read()
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            ELEVENLABS_URL,
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            data={"model_id": "scribe_v2"},
            files={"file": (audio.filename or "voicemail", data, audio.content_type or "application/octet-stream")},
        )
    if r.status_code != 200:
        raise HTTPException(502, f"ElevenLabs error {r.status_code}: {r.text[:300]}")
    return r.json()["text"]


@app.post("/analyze")
async def analyze(audio: UploadFile = File(...)):
    start = time.time()
    transcript = await transcribe(audio)
    return {"transcript": transcript, "seconds": round(time.time() - start, 1)}