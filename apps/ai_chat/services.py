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
    
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)
    
    # Gather key factory metrics to feed as context to the AI
    machines_down = Machine.objects.filter(status='UM').count()
    total_machines = Machine.objects.count()
    open_tickets = MaintenanceTicket.objects.filter(status='O').count()
    
    # Inventory
    critical_stock = WarehouseStock.objects.filter(quantity__lte=10000)
    stock_context = ", ".join([s.material for s in critical_stock]) if critical_stock else "None"
    
    # Production
    prod = ProductionLog.objects.aggregate(total_out=Sum('output_kg'), total_in=Sum('material_used'))
    yield_perc = (prod['total_out'] / prod['total_in'] * 100) if prod['total_in'] else 0
    
    # All Historical Data
    history_str = ""
    # Fetch distinct dates that have production data, ordered oldest to newest
    all_dates = ProductionLog.objects.values_list('date', flat=True).distinct().order_by('date')
    
    for hist_date in all_dates:
        hist_logs = ProductionLog.objects.filter(date=hist_date).select_related('machine', 'employee')
        h_out = sum(float(log.output_kg) for log in hist_logs)
        h_mat = sum(float(log.material_used) for log in hist_logs)
        h_tickets = MaintenanceTicket.objects.filter(opened_at__date=hist_date).count()
        history_str += f"  * {hist_date} (TOTALS): Output {h_out:.2f} kg, Material Used {h_mat:.2f} kg, Tickets Opened {h_tickets}\n"
        
        # Detailed breakdown
        for log in hist_logs:
            history_str += f"    - Machine {log.machine.code} ({log.machine.name}) | Employee: {log.employee.username}: Input {float(log.material_used):.2f} kg, Output {float(log.output_kg):.2f} kg\n"
    
    if not history_str:
        history_str = "  * No historical data available yet.\n"
        
    language_map = {'en': 'English', 'hi': 'Hindi', 'mr': 'Marathi'}
    language_name = language_map.get(user_language, 'English')
    
    context_str = (
        f"FACTORY METRICS:\n"
        f"Current System Date: {today}\n"
        f"- Uptime: {total_machines - machines_down}/{total_machines} Machines\n"
        f"- Open Tickets: {open_tickets}\n"
        f"- Critical Stock: {stock_context}\n"
        f"- Lifetime Yield: {yield_perc:.1f}%\n"
        f"- Financials: Selling Price = ₹50/kg, Raw Material Cost = ₹20/kg\n\n"
        f"HISTORICAL DATA (All Time):\n{history_str}\n"
        f"You are the PharmaERP AI Assistant. Your personality is extremely warm, friendly, and highly empathetic. You care deeply about the user and their factory.\n"
        f"You MUST respond completely in the {language_name} language.\n\n"
        f"Follow this exact formatting for ALL responses:\n"
        f"1. Start with a brief 1-sentence summary.\n"
        f"2. Use highlighted bullet points for detailed explanations.\n"
        f"3. If the user asks about machine warnings (e.g., vibration alerts) or errors, provide a full diagnostic explanation and clear suggestions to fix it.\n"
        f"4. End with a 1-sentence actionable conclusion.\n"
        f"5. Proactively provide strategic growth suggestions and operational optimizations based on the production data to increase yield and reduce costs.\n"
        f"Do NOT include fake diagrams or random characters. Keep it clean and professional."
    )
    return context_str

def generate_ai_response(prompt_text, user_language='en', model_choice='gemini-3.5-flash', chat_history=None):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        from apps.production.hf_service import get_hf_api_key, generate_hf_chat_fallback
        if get_hf_api_key():
            system_context = get_factory_context(user_language)
            hf_res = generate_hf_chat_fallback(prompt_text, system_context, user_language)
            if hf_res:
                return hf_res
        return "ERROR: GEMINI_API_KEY (or HUGGINGFACE_API_KEY / HF_TOKEN) environment variable not set."
        
    try:
        genai.configure(api_key=api_key)
        system_context = get_factory_context(user_language)
        
        history_text = ""
        if chat_history:
            history_text = "\n\nPAST CONVERSATION HISTORY:\n"
            for msg in chat_history:
                history_text += f"User: {msg.prompt}\nAI: {msg.response}\n\n"
                
        full_prompt = f"{system_context}{history_text}\n\nUSER QUESTION: {prompt_text}"
        
        try:
            # Attempt with user selected model
            model = genai.GenerativeModel(model_choice)
            response = model.generate_content(full_prompt)
            return response.text
        except Exception as inner_e:
            error_msg = str(inner_e)
            if '429' in error_msg or 'Quota exceeded' in error_msg:
                # Attempt with backup Gemini models
                backup_models = ['gemini-3.5-flash-lite', 'gemini-3.6-flash', 'gemini-3.7-flash', 'gemini-flash-lite-latest']
                for m in backup_models:
                    try:
                        fallback_model = genai.GenerativeModel(m)
                        response = fallback_model.generate_content(full_prompt)
                        return response.text
                    except Exception:
                        continue
                        
                # Check for Hugging Face fallback before giving up
                from apps.production.hf_service import get_hf_api_key, generate_hf_chat_fallback
                if get_hf_api_key():
                    hf_res = generate_hf_chat_fallback(prompt_text, system_context, user_language)
                    if hf_res:
                        return hf_res
                        
                return "⚠️ **API Limit Reached!**\n\nYou have exhausted the free-tier requests across all available fallback models. Please try again tomorrow!"
            raise inner_e
            
    except Exception as e:
        error_str = str(e)
        if '429' in error_str or 'Quota exceeded' in error_str:
            from apps.production.hf_service import get_hf_api_key, generate_hf_chat_fallback
            if get_hf_api_key():
                hf_res = generate_hf_chat_fallback(prompt_text, system_context, user_language)
                if hf_res:
                    return hf_res
            return "⚠️ **API Limit Reached!**\n\nYou have exhausted the free-tier requests. Please try again tomorrow!"
        return f"AI Error: Unable to process request. Details: {error_str}"

def generate_ai_audio(text):
    """Uses Gemini native TTS model to generate audio from text."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
        
    # Fix for TTS mispronouncing currency: explicitly replace ₹ with "Rupees"
    text = text.replace("₹", "Rupees ")
        
    try:
        genai.configure(api_key=api_key)
        tts_models = [
            'models/gemini-3.8-flash-lite-tts',
            'models/gemini-3.8-flash-tts',
            'models/gemini-3.1-flash-tts-preview',
            'models/gemini-2.5-flash-preview-tts'
        ]
        
        # Enforce a warm, friendly, and highly empathetic female voice
        voice_prompt = f"Read the following text aloud in a very warm, friendly, comforting, and empathetic female English voice. Speak gently and naturally with excellent human-like pronunciation. Do not change the voice or language. Text:\n{text}"
        
        for m in tts_models:
            try:
                model = genai.GenerativeModel(m)
                response = model.generate_content(voice_prompt)
                for candidate in response.candidates:
                    for part in candidate.content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data:
                            return part.inline_data.data
            except Exception as inner_e:
                # If this model hits 429 quota, try the next one in the list
                continue
                
        return None
    except Exception as e:
        print(f"TTS Error: {e}")
        return None
