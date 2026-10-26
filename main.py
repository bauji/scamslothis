import json
import os
import time

import httpx
import tinker
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

load_dotenv()
app = FastAPI()

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/speech-to-text"
MODEL = "Qwen/Qwen3.5-4B"
SYSTEM_PROMPT = """You check voicemail transcripts for scams.
Reply with JSON only, no other text, in exactly this shape:
{"verdict": "scam", "red_flags": ["short reason", "short reason"]}
verdict must be "scam" or "not_scam". Give up to 5 short red flags.
Use an empty red_flags list when the verdict is "not_scam"."""

_sampler = None
_tokenizer = None


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


async def get_model():
    global _sampler, _tokenizer
    if _sampler is None:
        service = tinker.ServiceClient()  # reads TINKER_API_KEY
        _sampler = await service.create_sampling_client_async(base_model=MODEL)
        _tokenizer = _sampler.get_tokenizer()
    return _sampler, _tokenizer


async def classify(transcript: str) -> dict:
    sampler, tokenizer = await get_model()
    tokens = tokenizer.apply_chat_template(
        conversation=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        add_generation_prompt=True,
        enable_thinking=False,
        return_dict=False,
    )
    result = await sampler.sample_async(
        prompt=tinker.types.ModelInput.from_ints(tokens),
        num_samples=1,
        sampling_params=tinker.types.SamplingParams(max_tokens=300, temperature=0.0),
    )
    reply = tokenizer.decode(result.sequences[0].tokens, skip_special_tokens=True)
    start, end = reply.find("{"), reply.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Model didn't return JSON: {reply[:200]}")
    data = json.loads(reply[start : end + 1])
    verdict = "scam" if data.get("verdict") == "scam" else "not_scam"
    flags = [str(f) for f in data.get("red_flags", [])][:5]
    return {"verdict": verdict, "red_flags": flags}


@app.post("/analyze")
async def analyze(audio: UploadFile = File(...)):
    start = time.time()
    transcript = await transcribe(audio)
    model_start = time.time()
    try:
        result = await classify(transcript)
    except Exception as e:
        return {"transcript": transcript, "error": str(e)[:300], "seconds": round(time.time() - start, 1)}
    return {
        "transcript": transcript,
        **result,
        "seconds": round(time.time() - start, 1),
        "model_seconds": round(time.time() - model_start, 1),
    }