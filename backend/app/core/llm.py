""""
Shared LLM client( Azure OpenAI) with a safe offline fallback.
of azure creds not set then it fall back to determenistic rule
alos appends any local TLS certs to the certifi bundle so HTTPS works behind a corporate proxy.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import certifi
from dotenv import load_dotenv
_BACKEND = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND / ".env")
load_dotenv()

# TLS proxy
_CERTS_DIRS= [_BACKEND / "certs", _BACKEND.parent / "certs"]

def _ensure_tls_trust() -> None:
    bundle = Path(certifi.where())
    try:
        text = bundle.read_text(encoding="utf-8", errors="ignore")
        for cert_dir in _CERTS_DIRS:
            if not cert_dir.exists():
                continue
            for crt in sorted(cert_dir.glob("*.crt")):
                if f"# >>> {crt.name}" in text:
                    continue
                with  bundle.open("a" , encoding="utf-8") as f:
                    f.write(f"\n# >>> {crt.name}\n{crt.read_text(errors='ignore')}")
                text += f"# >>> {crt.name}"
    except PermissionError:
        pass
    os.environ.setdefault("SSL_CERT_FILE", str(bundle))
    os.environ.setdefault("REQUESTS_CA_BUNDLE", str(bundle))

def available() -> bool:
    return bool(os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY"))

def embeddings_available() -> bool:
    return available() and bool(os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"))

def _client():
    _ensure_tls_trust()
    from openai import AzureOpenAI

    return AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    )

def _deployment() -> str:
    return os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

def azure_openai_client():
    """Return ``(client, deployment)`` or ``None`` if Azure is not configured.

    Used by the media tools for Whisper transcription and GPT-4o frame captions.
    """
    if not available():
        return None
    return _client(), _deployment()



def chat_json(system: str, user: str, *, temperature: float = 0.2) -> dict[str, Any] | None:
    """Call the LLM and parse a JSON object response. None if unavailable."""
    if not available():
        return None
    client = _client()
    model = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    resp = client.chat.completions.create(
        model=_deployment(),
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    content = resp.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def chat_text(system: str, user: str, *, temperature: float = 0.3) -> str | None:
    """Call the LLM for a plain-text answer. None if unavailable."""
    if not available():
        return None
    client = _client()
    resp = client.chat.completions.create(
        model=_deployment(),
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (resp.choices[0].message.content or "").strip() or None

def embed(texts: list[str], *, batch: int = 64) -> list[list[float]] | None:
    """Embed a list of texts. None if no embedding deployment is configured."""
    if not embeddings_available() or not texts:
        return None
    client = _client()
    deployment = os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"]
    clean = [(t if t and t.strip() else " ") for t in texts]
    out: list[list[float]] = []
    try:
        for i in range(0, len(clean), batch):
            resp = client.embeddings.create(model=deployment, input=clean[i:i + batch])
            out.extend(d.embedding for d in resp.data)
    except Exception:
        return None
    return out