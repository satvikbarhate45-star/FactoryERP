from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from apps.accounts.decorators import role_required
import markdown
import re
import base64
from .models import ChatLog
from .services import generate_ai_response, generate_ai_audio
from django.contrib.auth import get_user_model

User = get_user_model()

@login_required(login_url='/login/')
@role_required('PM')
def chat_interface(request):
    context = {'user_lang': getattr(request.user, 'language', 'en')}
    return render(request, 'ai_chat.html', context)

@login_required(login_url='/login/')
def api_chat(request):
    if request.method == 'POST':
        prompt = request.POST.get('prompt', '')
        model_choice = request.POST.get('model', 'gemini-3.5-flash')
        if not prompt:
            return JsonResponse({'error': 'No prompt provided'}, status=400)
            
        # Get AI response
        user = request.user if request.user.is_authenticated else User.objects.first()
        user_lang = getattr(user, 'language', 'en')
        chat_history = reversed(ChatLog.objects.filter(user=user).order_by('-created_at')[:5])
        raw_response = generate_ai_response(prompt, user_lang, model_choice, chat_history=chat_history)
        
        # Convert markdown response to HTML for rendering in the chat
        html_response = markdown.markdown(raw_response)
        
        # Generate Audio inline to save a round-trip if requested
        audio_b64 = ""
        if request.POST.get('voice_enabled') == 'true':
            audio_data = generate_ai_audio(raw_response)
            if audio_data:
                audio_b64 = base64.b64encode(audio_data).decode('utf-8') if isinstance(audio_data, bytes) else audio_data
        
        # Log it (FR-8.4)
        user = request.user if request.user.is_authenticated else User.objects.first()
        ChatLog.objects.create(
            user=user,
            prompt=prompt,
            response=raw_response
        )
        
        return JsonResponse({
            'response': html_response, 
            'raw_response': raw_response,
            'audio_base64': audio_b64
        })
    return JsonResponse({'error': 'Invalid method'}, status=405)

@login_required(login_url='/login/')
def api_tts(request):
    if request.method == 'POST':
        text = request.POST.get('text', '')
        if not text:
            return JsonResponse({'error': 'No text provided'}, status=400)
            
        # Generate Native Gemini Audio
        audio_data = generate_ai_audio(text)
        audio_b64 = ""
        if audio_data:
            if isinstance(audio_data, bytes):
                audio_b64 = base64.b64encode(audio_data).decode('utf-8')
            else:
                audio_b64 = audio_data
                
        return JsonResponse({'audio_base64': audio_b64})
    return JsonResponse({'error': 'Invalid method'}, status=405)
