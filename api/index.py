import os
import sys

# Ensure the root project directory is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import app as flask_app


class VercelPathMiddleware:
    """
    WSGI middleware for Vercel Serverless deployments.
    Vercel internal rewrites route requests to /api/index.
    This middleware restores the original request path from X-Forwarded-Uri,
    X-Matched-Path, or by stripping the /api/index prefix.
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')

        # Check for original URI forwarded by Vercel
        forwarded_uri = (
            environ.get('HTTP_X_FORWARDED_URI')
            or environ.get('HTTP_X_VERCEL_FORWARDED_FOR_PATH')
            or environ.get('HTTP_X_MATCHED_PATH')
        )

        if forwarded_uri and not forwarded_uri.startswith('/api/index'):
            path = forwarded_uri.split('?')[0]
        elif path.startswith('/api/index.py'):
            path = path[len('/api/index.py'):]
        elif path.startswith('/api/index'):
            path = path[len('/api/index'):]

        environ['PATH_INFO'] = path if path else '/'
        return self.wsgi_app(environ, start_response)


# Export the wrapped WSGI application
app = VercelPathMiddleware(flask_app)
