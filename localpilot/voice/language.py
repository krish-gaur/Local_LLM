"""Conservative Hindi/English/Hinglish language preference and reply helpers."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class VoiceLanguage(str, Enum):
    AUTO = "auto"
    HINDI = "hi"
    ENGLISH = "en"
    HINGLISH = "hinglish"


_HINGLISH = {"karo", "bolo", "batao", "samjhao", "ruko", "suno", "mein", "par", "sabse",
             "sasti", "gaadi", "car", "teen", "website", "kya", "kaise", "ab"}


def detect_language(text: str, model_language: str | None = None) -> VoiceLanguage:
    if re.search(r"[\u0900-\u097f]", text): return VoiceLanguage.HINDI
    words = set(re.findall(r"[a-z]+", text.lower()))
    if len(words & _HINGLISH) >= 2: return VoiceLanguage.HINGLISH
    if model_language and model_language.lower().startswith("hi"): return VoiceLanguage.HINDI
    return VoiceLanguage.ENGLISH


def language_command(text: str) -> VoiceLanguage | None:
    lowered = text.lower()
    if "english mein" in lowered or "english me" in lowered or "speak english" in lowered:
        return VoiceLanguage.ENGLISH
    if "hindi mein" in lowered or "hindi me" in lowered or "हिंदी" in text:
        return VoiceLanguage.HINDI
    if "hinglish" in lowered: return VoiceLanguage.HINGLISH
    return None


def is_cancel_command(text: str) -> bool:
    lowered = text.lower().strip()
    return any(phrase in lowered for phrase in ("cancel", "stop task", "ruko", "रुको", "cancel karo"))


def is_stop_listening_command(text: str) -> bool:
    lowered = text.lower().strip()
    return any(phrase in lowered for phrase in ("stop listening", "sunna band", "सुनना बंद", "exit jean grey"))


def acknowledgement(language: VoiceLanguage) -> str:
    if language == VoiceLanguage.ENGLISH: return "I'm listening. What can I do for you?"
    return "Haan, bolo. Main sun rahi hoon. What can I do for you?"


def concise_status(status: str, language: VoiceLanguage, detail: str = "") -> str:
    if language == VoiceLanguage.HINDI:
        if status == "COMPLETED": return f"काम सत्यापित हो गया। {detail}".strip()
        if status == "WAITING_FOR_APPROVAL": return "इस कार्रवाई के लिए आपकी स्पष्ट अनुमति चाहिए।"
        if status == "CANCELLED": return "ठीक है, कार्य रद्द कर दिया।"
        return f"कार्य पूरा नहीं हुआ। {detail}".strip()
    if language == VoiceLanguage.HINGLISH:
        if status == "COMPLETED": return f"Kaam verify ho gaya. {detail}".strip()
        if status == "WAITING_FOR_APPROVAL": return "Is action ke liye aapki approval chahiye."
        if status == "CANCELLED": return "Theek hai, task cancel kar diya."
        return f"Task complete nahi hua. {detail}".strip()
    if status == "COMPLETED": return f"The verified task completed. {detail}".strip()
    if status == "WAITING_FOR_APPROVAL": return "This action needs your explicit approval."
    if status == "CANCELLED": return "The task was cancelled."
    return f"The task did not complete. {detail}".strip()
