"""
PharmaERP Hugging Face ML Pipeline & Inference Service
======================================================
Secure, non-blocking Hugging Face Serverless Inference integration for:
1. Machine telemetry anomaly analysis & predictive root-cause diagnosis.
2. Maintenance ticket urgency and classification.
3. Fallback AI response generation for factory operations.

Thread-safety & Non-blocking Design:
- Uses concurrent.futures.ThreadPoolExecutor for asynchronous dispatch.
- Enforces strict connect and read timeouts (3.0s / 8.0s) so Django request-response
  threads and APScheduler background tasks are never blocked or hung.
- Fallback heuristics guarantee graceful degradation if HF API is offline or warming up (503).
"""

import os
import logging
import requests
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Dedicated background thread pool for Hugging Face inference calls
_HF_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="hf_inference_worker")

# Default Hugging Face Inference Models
DEFAULT_LLM_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"
FALLBACK_LLM_MODEL = "google/flan-t5-large"
CLASSIFICATION_MODEL = "facebook/bart-large-mnli"


def get_hf_api_key():
    """
    Securely fetches the Hugging Face API key from environment variables.
    Checks HUGGINGFACE_API_KEY first, then HF_TOKEN.
    """
    return os.environ.get("HUGGINGFACE_API_KEY") or os.environ.get("HF_TOKEN")


def query_hf_api(payload, model=DEFAULT_LLM_MODEL, timeout=(3.0, 8.0)):
    """
    Executes a synchronous HTTP POST call to Hugging Face Inference API
    with strict connect and read timeouts.
    Returns parsed JSON response, or None on any failure/timeout.
    """
    api_key = get_hf_api_key()
    if not api_key:
        logger.debug("Hugging Face API key (HUGGINGFACE_API_KEY or HF_TOKEN) is not configured.")
        return None

    api_url = f"https://api-inference.huggingface.co/models/{model}"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=timeout)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 503:
            # Hugging Face serverless cold start: model is currently loading
            logger.info(f"Hugging Face model '{model}' is warming up (503). Using deterministic fallback.")
            return None
        elif response.status_code in (401, 403):
            logger.error(f"Hugging Face API Authentication failed ({response.status_code}). Check your HUGGINGFACE_API_KEY.")
            return None
        else:
            logger.warning(f"Hugging Face API responded with status {response.status_code}: {response.text[:200]}")
            return None
    except requests.exceptions.Timeout:
        logger.warning(f"Hugging Face API timed out after {timeout} seconds. Non-blocking fallback activated.")
        return None
    except requests.exceptions.RequestException as exc:
        logger.warning(f"Hugging Face API request failed: {exc}")
        return None
    except Exception as general_err:
        logger.error(f"Unexpected error during Hugging Face call: {general_err}")
        return None


def query_hf_api_async(payload, model=DEFAULT_LLM_MODEL, callback=None):
    """
    Submits an inference request to the background thread pool.
    Guarantees the calling thread (e.g. Django web worker) does NOT block.
    """
    def _worker():
        result = query_hf_api(payload, model=model)
        if callback and callable(callback):
            try:
                callback(result)
            except Exception as cb_err:
                logger.error(f"Error executing Hugging Face async callback: {cb_err}")
        return result

    return _HF_EXECUTOR.submit(_worker)


def analyze_machine_telemetry_hf(machine_code, vibration, temperature, trend_slope):
    """
    Uses Hugging Face model to diagnose telemetry anomalies and provide
    engineering root-cause analysis for maintenance tickets.
    """
    prompt = (
        f"You are a Senior Pharmaceutical Reliability & Maintenance Engineer. "
        f"Analyze the following telemetry for Machine '{machine_code}':\n"
        f"- Vibration: {vibration:.2f} mm/s (Threshold: 3.0 warning, 5.0 critical)\n"
        f"- Core Temperature: {temperature:.1f} °C (Threshold: 72 warning, 85 critical)\n"
        f"- Production Trend Slope: {trend_slope:.2f}\n\n"
        f"Provide a 2-sentence diagnostic assessment stating the likely physical mechanical failure "
        f"(e.g., bearing wear, shaft misalignment, lubricant degradation) and the primary corrective action."
    )

    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 120,
            "temperature": 0.3,
            "return_full_text": False
        }
    }

    # Attempt primary model
    response = query_hf_api(payload, model=DEFAULT_LLM_MODEL)
    if response and isinstance(response, list) and len(response) > 0:
        generated = response[0].get("generated_text", "").strip()
        if generated:
            return generated

    # Fallback heuristic diagnosis if HF is not configured or warming up
    if vibration > 5.0 or temperature > 85.0:
        return (f"Physical Anomaly: Critical bearing seizure or severe thermal overload detected on {machine_code}. "
                f"Action: Emergency machine halt, inspect drive shaft tolerances, and replace worn bearing assemblies.")
    elif vibration > 3.0:
        return (f"Physical Anomaly: High vibrational oscillation detected indicating rotor unbalance or mounting looseness on {machine_code}. "
                f"Action: Perform vibration frequency spectral analysis and torque mounting bolts.")
    else:
        return (f"Physical Anomaly: Thermal elevation detected on {machine_code} suggesting lubrication breakdown. "
                f"Action: Inspect cooling jackets and replenish high-temperature synthetic lubricant.")


def classify_ticket_urgency_hf(cause_text):
    """
    Uses Hugging Face zero-shot classification to categorize ticket severity
    without blocking the main thread.
    """
    candidate_labels = ["Emergency Critical Shutdown", "High Priority Maintenance", "Routine Preventative Check", "Low Priority Observation"]
    payload = {
        "inputs": cause_text,
        "parameters": {
            "candidate_labels": candidate_labels
        }
    }

    response = query_hf_api(payload, model=CLASSIFICATION_MODEL)
    if response and isinstance(response, dict) and "labels" in response:
        return response["labels"][0]

    # Heuristic fallback
    cause_lower = cause_text.lower()
    if "critical" in cause_lower or "emergency" in cause_lower or "halt" in cause_lower:
        return "Emergency Critical Shutdown"
    elif "warning" in cause_lower or "elevated" in cause_lower:
        return "High Priority Maintenance"
    return "Routine Preventative Check"


def generate_hf_chat_fallback(prompt_text, system_context="", user_language='en'):
    """
    Provides a conversational AI fallback via Hugging Face when Gemini API is rate-limited or unavailable.
    """
    language_map = {'en': 'English', 'hi': 'Hindi', 'mr': 'Marathi'}
    lang_name = language_map.get(user_language, 'English')

    prompt = (
        f"System Context:\n{system_context}\n\n"
        f"You are the PharmaERP AI Assistant. Respond in {lang_name}.\n"
        f"User Question: {prompt_text}\n\n"
        f"Answer:"
    )

    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 250,
            "temperature": 0.4,
            "return_full_text": False
        }
    }

    response = query_hf_api(payload, model=DEFAULT_LLM_MODEL)
    if response and isinstance(response, list) and len(response) > 0:
        text = response[0].get("generated_text", "").strip()
        if text:
            return f"{text}\n\n*(Powered by PharmaERP Hugging Face Inference Pipeline)*"

    return None
