from __future__ import annotations

import json
import os
from pathlib import Path

ALLOWED_KEYS = {
    "AI_PROVIDER","AI_ENABLE","OPENROUTER_API_KEY","OPENROUTER_API_KEY_FILE","OPENROUTER_MODEL","OPENROUTER_FALLBACK_MODELS",
    "QWEN_ENABLE","DASHSCOPE_API_KEY","QWEN_BASE_URL","QWEN_MODEL",
    "GOOGLE_CLIENT_ID","GOOGLE_CLIENT_SECRET","GOOGLE_REDIRECT_URI",
    "WHATSAPP_ENABLE","WHATSAPP_ACCESS_TOKEN","WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_SENDER_PHONE","WHATSAPP_GRAPH_VERSION",
    "ADMIN_EMAIL","CATATRIAGE_PUBLIC_URL","GMAIL_APP_PASSWORD","GMAIL_APP_PASSWORD_FILE","GMAIL_OAUTH_JSON","GMAIL_OAUTH_JSON_FILE",
    "WHATSAPP_SURGERY_TEMPLATE","WHATSAPP_TEMPLATE_LANGUAGE","WHATSAPP_DOCTOR_CONFIG_JSON","WHATSAPP_DOCTOR_CONFIG_JSON_FILE",
}


def load_local_config() -> None:
    path=Path(__file__).resolve().parent/"data"/"integrations.json"
    if not path.exists(): return
    settings=json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(settings,dict): raise ValueError("Integration settings must be a JSON object.")
    for key,value in settings.items():
        if key in ALLOWED_KEYS and isinstance(value,str) and value.strip():
            os.environ.setdefault(key,value.strip())


def model_label(model: str) -> str:
    names={
        "google/gemma-4-31b-it:free":"Gemma 4 31B",
        "google/gemma-4-26b-a4b-it:free":"Gemma 4 26B",
        "nvidia/nemotron-3.5-super-vl:free":"NVIDIA Nemotron 3.5 Super VL",
    }
    return names.get(model,model)+" via OpenRouter"


def advisory_settings() -> dict:
    provider=os.getenv("AI_PROVIDER","").strip().lower()
    if not provider:
        provider="openrouter" if os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY_FILE") else "qwen"
    if provider not in {"openrouter","qwen"}:
        return {"enabled":False,"provider":provider,"label":"AI scheduling","api_key":"","base_url":"","model":"","error":"Unsupported scheduling provider."}
    flag=os.getenv("AI_ENABLE",os.getenv("QWEN_ENABLE",""))
    enabled=flag.strip().lower() in {"1","true","yes"}
    if provider=="openrouter":
        key=os.getenv("OPENROUTER_API_KEY","").strip()
        key_file=os.getenv("OPENROUTER_API_KEY_FILE","").strip()
        error=None
        if not key and key_file:
            try:
                raw=Path(key_file).read_text(encoding="utf-8-sig").strip()
                if raw.startswith("{"):
                    data=json.loads(raw)
                    key=str(data.get("OPENROUTER_API_KEY",data.get("DASHSCOPE_API_KEY",""))).strip()
                else:
                    # Accept a plain key file or a KEY=value line without printing it.
                    for line in raw.splitlines():
                        line=line.strip()
                        if line.startswith("OPENROUTER_API_KEY="): line=line.split("=",1)[1].strip().strip('"').strip("'")
                        if line.startswith("sk-or-"):
                            key=line
                            break
            except (OSError,ValueError):
                error="The configured OpenRouter key file could not be read."
        model=os.getenv("OPENROUTER_MODEL","google/gemma-4-31b-it:free")
        # Only explicitly configured free variants are eligible for fallback.
        fallback_models=[m.strip() for m in os.getenv("OPENROUTER_FALLBACK_MODELS","").split(",")
            if m.strip().endswith(":free") and m.strip()!=model][:1]
        return {"enabled":enabled,"provider":"openrouter","label":model_label(model),"api_key":key,
            "base_url":"https://openrouter.ai/api/v1","model":model,"fallback_models":fallback_models,"error":error}
    return {"enabled":enabled,"provider":"qwen","label":"Qwen","api_key":os.getenv("DASHSCOPE_API_KEY","").strip(),
        "base_url":os.getenv("QWEN_BASE_URL","").strip().rstrip("/"),"model":os.getenv("QWEN_MODEL","qwen-plus"),"error":None}
