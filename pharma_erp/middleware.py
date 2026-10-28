"""
PharmaERP Network Resilience & Smart Timeout Middleware
======================================================
Prevents false-positive offline errors by:
1. Detecting PostgreSQL / Supabase connection drops or pooler timeouts.
2. Performing active socket probes with IPv4/IPv6 support to verify genuine connectivity.
3. Automatically resetting stale connections and retrying active requests
   gracefully without breaking user sessions.
4. Distinguishing connection drops from data/schema errors so SQL errors are not masked.
"""

import socket
import time
import logging
from django.db import connections
from django.db.utils import OperationalError, InterfaceError
from django.http import JsonResponse
from django.shortcuts import render

logger = logging.getLogger(__name__)


def get_db_host_port():
    try:
        from django.conf import settings
        db_config = settings.DATABASES.get('default', {})
        host = db_config.get('HOST') or 'db.mnlzpgdeaqmzitcgvzqh.supabase.co'
        port = int(db_config.get('PORT') or 5432)
        return host, port
    except Exception:
        return 'db.mnlzpgdeaqmzitcgvzqh.supabase.co', 5432


def is_internet_reachable(timeout=2.0):
    """
    Fast, reliable network probe supporting both IPv4 and IPv6.
    Checks reachability to Supabase or public HTTPS roots (port 443).
    """
    host, port = get_db_host_port()
    if not host or 'sqlite' in str(host).lower():
        return True

    targets = [(host, port), ('1.1.1.1', 443), ('8.8.8.8', 443)]
    for h, p in targets:
        try:
            sock = socket.create_connection((h, p), timeout=timeout)
            sock.close()
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
        except (OperationalError, InterfaceError) as exc:
            return self.handle_database_exception(request, exc)

    def process_exception(self, request, exception):
        """Handle unhandled connection exceptions bubbling up from views."""
        if isinstance(exception, (OperationalError, InterfaceError)):
            return self.handle_database_exception(request, exception)
        return None

    def handle_database_exception(self, request, exc):
        """
        Smart resolution strategy:
        1. Check if the error is a connection drop/stale pool connection.
        2. If network is active, reset connections and retry request once.
        3. If genuinely offline, return a polished 503 response.
        """
        exc_str = str(exc).lower()
        is_conn_error = any(kw in exc_str for kw in [
            'connection', 'closed', 'timeout', 'terminated',
            'could not connect', 'broken pipe', 'server closed', 'reset by peer'
        ])

        logger.warning(f"[NETWORK RESILIENCE] Database exception encountered: {exc}")

        # Check if internet/Supabase is reachable
        if is_internet_reachable(timeout=2.0):
            logger.info("[NETWORK RESILIENCE] Internet/Supabase is reachable. Stale connection or pooler drop detected. Resetting connection pool...")
            try:
                connections.close_all()
                time.sleep(0.3)
                # Retry request once
                return self.get_response(request)
            except Exception as retry_exc:
                logger.error(f"[NETWORK RESILIENCE] Reconnection retry attempt failed: {retry_exc}")
                if not is_conn_error:
                    # Let real non-connection errors surface rather than masquerading as offline
                    raise retry_exc

        if not is_conn_error:
            # Re-raise non-connection errors so standard Django debugging / 500 handlers report the actual issue
            raise exc

        # Genuine disconnect or hard timeout reached
        logger.error("[NETWORK RESILIENCE] Remote database unreachable. Rendering clean offline interface.")

        is_ajax = (
            request.headers.get('x-requested-with') == 'XMLHttpRequest' or
            request.headers.get('accept', '').startswith('application/json') or
            request.path.startswith('/api/')
        )

        if is_ajax:
            return JsonResponse({
                'status': 'offline',
                'error': 'network_disconnected',
                'message': 'Database connection temporarily interrupted. Please retry in a few seconds.',
                'retry': True
            }, status=503)

        response = render(request, 'network_error.html', status=503)
        response['Retry-After'] = '5'
        return response
