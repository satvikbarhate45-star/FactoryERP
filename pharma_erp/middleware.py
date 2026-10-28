"""
PharmaERP Network Resilience & Smart Timeout Middleware
======================================================
Prevents false-positive offline errors by:
1. Detecting PostgreSQL / Supabase connection or query timeout errors.
2. Performing an active socket probe to differentiate between temporary
   network lag/socket drop vs. a genuine internet outage.
3. Automatically resetting stale connections and retrying active requests
   gracefully without breaking user sessions.
4. If the connection is genuinely offline or permanently unreachable,
   cleanly rendering the branded PharmaERP offline recovery screen with
   an interactive Retry button, avoiding raw 500 error pages.
"""

import socket
import time
import logging
from django.db import connections
from django.db.utils import OperationalError, DatabaseError, InterfaceError
from django.http import JsonResponse
from django.shortcuts import render

logger = logging.getLogger(__name__)

# Primary Supabase host and fallback DNS probe
def get_db_host_port():
    try:
        from django.conf import settings
        db_config = settings.DATABASES.get('default', {})
        host = db_config.get('HOST') or 'db.mnlzpgdeaqmzitcgvzqh.supabase.co'
        port = int(db_config.get('PORT') or 5432)
        return host, port
    except Exception:
        return 'db.mnlzpgdeaqmzitcgvzqh.supabase.co', 5432


def is_internet_reachable(timeout=1.5):
    """
    Fast, non-blocking network probe.
    Checks reachability to configured Supabase host or public DNS root.
    """
    host, port = get_db_host_port()
    if not host or 'sqlite' in str(host).lower():
        return True

    targets = [(host, port), ('1.1.1.1', 53), ('8.8.8.8', 53)]
    for h, p in targets:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((h, p))
            s.close()
            return True
        except (socket.timeout, OSError):
            continue
    return False


class NetworkResilienceMiddleware:
    """
    Enterprise middleware ensuring zero false-positive connection errors
    and graceful fail-fast handling for real network disconnects.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except (OperationalError, DatabaseError, InterfaceError) as exc:
            return self.handle_database_exception(request, exc)

    def process_exception(self, request, exception):
        """Handle unhandled database exceptions bubbling up from views."""
        if isinstance(exception, (OperationalError, DatabaseError, InterfaceError)):
            return self.handle_database_exception(request, exception)
        return None

    def handle_database_exception(self, request, exc):
        """
        Smart resolution strategy:
        1. Check if the error is temporary network lag or connection pool drop.
        2. If internet is reachable, reset the connection and retry the request.
        3. If genuinely offline, return a polished 503 response.
        """
        logger.warning(f"[NETWORK RESILIENCE] Database query interrupted: {exc}")

        # Check if internet/Supabase is reachable (avoid false positive)
        if is_internet_reachable(timeout=1.5):
            logger.info("[NETWORK RESILIENCE] Network is active. Stale connection or pooler drop detected. Resetting connection...")
            try:
                # Reset stale connections cleanly
                connections.close_all()
                time.sleep(0.2)
                # Only re-execute GET requests safely (idempotent); for POST requests let caller see clean error
                if request.method == 'GET':
                    return self.get_response(request)
            except Exception as retry_exc:
                logger.error(f"[NETWORK RESILIENCE] Reconnection retry failed: {retry_exc}")


        # Genuine disconnect or hard timeout reached
        logger.error("[NETWORK RESILIENCE] Internet connection lost or server unreachable. Rendering clean offline interface.")

        # Intercept AJAX / API requests with structured JSON
        is_ajax = (
            request.headers.get('x-requested-with') == 'XMLHttpRequest' or
            request.headers.get('accept', '').startswith('application/json') or
            request.path.startswith('/api/')
        )

        if is_ajax:
            return JsonResponse({
                'status': 'offline',
                'error': 'network_disconnected',
                'message': 'Internet Connection Lost or Request Timed Out. Please check your network.',
                'retry': True
            }, status=503)

        # Intercept HTML browser navigation with polished error banner
        response = render(request, 'network_error.html', status=503)
        response['Retry-After'] = '5'
        return response
