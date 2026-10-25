import logging
from django.core.exceptions import PermissionDenied
from functools import wraps
from django.shortcuts import render

logger = logging.getLogger(__name__)

def role_required(*allowed_roles):
    """
    Decorator for views that checks that the user has a specific role,
    returning a 403 (PermissionDenied) if not. FR-1.3 requires this to be logged.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return view_func(request, *args, **kwargs) # Handled by @login_required

            # Admin 'AD' generally has access to everything per PRD
            if request.user.role == 'AD' or request.user.role in allowed_roles:
                return view_func(request, *args, **kwargs)
            
            # Log the unauthorized access (FR-1.3)
            logger.warning(f"UNAUTHORIZED ACCESS (403): User '{request.user.username}' (Role: {request.user.role}) attempted to access {request.path}.")
            
            # Raise 403 Forbidden
            raise PermissionDenied("You do not have permission to access this page.")
            
        return _wrapped_view
    return decorator
