import os
import google.generativeai as genai
from django.db.models import Sum, Avg
from apps.maintenance.models import Machine, MaintenanceTicket
from apps.inventory.models import WarehouseStock
from apps.production.models import ProductionLog


# GEMINI_API_KEY should be set in .env or system environment variables

def get_factory_context(user_language='en'):
    from django.utils import timezone
    from datetime import timedelta
    from django.core.cache import cache
    
    cache_key = f"ai_factory_context_{user_language}"
    cached_ctx = cache.get(cache_key)
    if cached_ctx:
        return cached_ctx
        
    today = timezone.localdate()
    
    # 1. Quick aggregate metrics
    machines_down = Machine.objects.filter(status='UM').count()
    total_machines = Machine.objects.count()
    open_tickets = MaintenanceTicket.objects.filter(status='O').count()
    
    # 2. Critical Inventory Stock
    critical_stock = WarehouseStock.objects.filter(quantity__lte=10000)[:5]
    stock_context = ", ".join([f"{s.material} ({s.quantity} units)" for s in critical_stock]) if critical_stock else "All materials sufficiently stocked"
    
    # 3. Overall Production Yield
    prod = ProductionLog.objects.aggregate(total_out=Sum('output_kg'), total_in=Sum('material_used'))
    yield_perc = (prod['total_out'] / prod['total_in'] * 100) if (prod and prod.get('total_in')) else 0
    
    # 4. Recent Production Activity (Last 8 logs in a single fast query)
    recent_logs = ProductionLog.objects.select_related('machine', 'employee').order_by('-date')[:8]
    recent_summary = []
    for log in recent_logs:
        emp_name = log.employee.username if log.employee else 'Operator'
        mach_name = log.machine.code if log.machine else 'Machine'
        recent_summary.append(f"- {log.date}: Machine {mach_name} | {emp_name} | Input: {float(log.material_used):.1f}kg, Output: {float(log.output_kg):.1f}kg")
    
    recent_str = "\n".join(recent_summary) if recent_summary else "- No recent production logs recorded."
        
    language_map = {'en': 'English', 'hi': 'Hindi', 'mr': 'Marathi'}
    language_name = language_map.get(user_language, 'English')
    
    context_str = (
        f"FACTORY OPERATIONAL METRICS:\n"
        f"Current System Date: {today}\n"
        f"- Machine Status: {total_machines - machines_down}/{total_machines} Operational ({machines_down} Down/Under Maintenance)\n"
        f"- Active Maintenance Tickets: {open_tickets}\n"
        f"- Critical Inventory: {stock_context}\n"
        f"- Overall Yield Rate: {yield_perc:.1f}%\n"
        f"- Standard Financials: Selling Price = ₹50/kg, Raw Material Cost = ₹20/kg\n\n"
        f"RECENT BATCH RUNS:\n{recent_str}\n\n"
        f"You are the PharmaERP AI Assistant. You are warm, empathetic, and knowledgeable.\n"
        f"You MUST respond completely in {language_name}.\n"
        f"Keep responses clear, professional, well-formatted with bullet points, and concise."
    )
    cache.set(cache_key, context_str, 90)  # Cache for 90 seconds
    return context_str

def get_gemini_api_key():
    """Fetches Gemini API key from standard environment variables."""
    return (
        os.environ.get("GEMINI_API_KEY") or
        os.environ.get("GOOGLE_API_KEY") or
        os.environ.get("GEMINI_KEY") or
        os.environ.get("GOOGLE_AI_KEY")
    )


def generate_ai_response(prompt_text, user_language='en', model_choice='gemini-1.5-flash', chat_history=None):
    api_key = get_gemini_api_key()
    system_context = get_factory_context(user_language)
    
    # Priority order of Gemini models
    # Always include gemini-2.5-flash and gemini-1.5-flash
    candidate_models = ['gemini-2.5-flash', 'gemini-1.5-flash', 'gemini-flash-latest', 'gemini-2.5-pro', 'gemini-1.5-pro']
    if 'pro' in (model_choice or '').lower():
        candidate_models = ['gemini-2.5-pro', 'gemini-1.5-pro', 'gemini-2.5-flash', 'gemini-1.5-flash']

    history_text = ""
    if chat_history:
        history_text = "\n\nPAST CONVERSATION HISTORY:\n"
        for msg in chat_history:
            history_text += f"User: {msg.prompt}\nAI: {msg.response}\n\n"
            
    full_prompt = f"{system_context}{history_text}\n\nUSER QUESTION: {prompt_text}"
    
    if api_key:
        try:
            genai.configure(api_key=api_key)
            for m in candidate_models:
                try:
                    model = genai.GenerativeModel(m)
                    response = model.generate_content(full_prompt)
                    if response and response.text:
                        return response.text
                except Exception as inner_e:
                    continue
        except Exception:
            pass

    # Fallback to Hugging Face if Gemini is unreachable
    try:
        from apps.production.hf_service import get_hf_api_key, generate_hf_chat_fallback
        if get_hf_api_key():
            hf_res = generate_hf_chat_fallback(prompt_text, system_context, user_language)
            if hf_res:
                return hf_res
    except Exception:
        pass

    # Graceful localized fallback message
    if user_language == 'mr':
        return (
            "⚠️ **एआय सहाय्यक सूचना**\n\n"
            "सध्या एआय सर्व्हरशी तात्पुरता संपर्क होऊ शकला नाही. कृपया थोड्या वेळाने पुन्हा विचारून पहा, "
            "किंवा Render डॅशबोर्डमध्ये `GEMINI_API_KEY` बरोबर कॉन्फिगर असल्याची खात्री करा."
        )
    elif user_language == 'hi':
        return (
            "⚠️ **एआई सहायक सूचना**\n\n"
            "वर्तमान में एआई सर्वर के साथ अस्थायी नेटवर्क समस्या है। कृपया कुछ पलों बाद पुनः प्रयास करें।"
        )
    else:
        return (
            "⚠️ **AI Assistant Notice**\n\n"
            "External AI network request temporarily timed out. Please try again in a few moments."
        )


def generate_ai_audio(text):
    """Uses available TTS or returns None so browser speech synthesis takes over seamlessly."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
        
    text = text.replace("₹", "Rupees ")
    tts_models = [
        'models/gemini-2.5-flash-preview-tts',
        'models/gemini-2.0-flash-exp'
    ]
    try:
        genai.configure(api_key=api_key, transport='rest')
        voice_prompt = f"Read the following text aloud in a very warm, friendly, comforting, and empathetic female English voice:\n{text}"
        for m in tts_models:
            try:
                model = genai.GenerativeModel(m)
                response = model.generate_content(voice_prompt)
                for candidate in response.candidates:
                    for part in candidate.content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data:
                            return part.inline_data.data
            except Exception:
                continue
    except Exception:
        pass
    return None

