import os
from flask import Flask, render_template, session, jsonify
from config import Config
from database.connection import init_db, is_database_configured
from services.prediction_service import prediction_service
from routes.auth_routes import auth_bp
from routes.prediction_routes import predict_bp
from routes.history_routes import history_bp
from routes.admin_routes import admin_bp


def create_app():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    app = Flask(
        __name__,
        template_folder=os.path.join(base_dir, 'templates'),
        static_folder=os.path.join(base_dir, 'static'),
        static_url_path='/static'
    )
    app.config.from_object(Config)

    # 1. Initialize Database Schema (Non-blocking on Vercel cold-starts)
    is_vercel = os.getenv('VERCEL') == '1' or os.getenv('VERCEL_ENV') is not None
    if not is_vercel:
        with app.app_context():
            try:
                init_db()
            except Exception as e:
                print(f"[App Warning] Database initialization deferred: {e}")

    # 2. Pre-warm Prediction Service (Model and Vectorizer in memory)
    try:
        _ = prediction_service.model
        print("[App] ML Model and TF-IDF Vectorizer pre-warmed and ready.")
    except Exception as e:
        print(f"[App Warning] Could not pre-warm ML model: {e}")

    # 3. Context Processor for Global Template Context (User Session)
    @app.context_processor
    def inject_user():
        user = None
        if 'user_id' in session:
            user = {
                "id": session.get('user_id'),
                "name": session.get('user_name'),
                "email": session.get('user_email'),
                "role": session.get('user_role')
            }
        return dict(current_user=user)

    # 4. Register Blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(predict_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(admin_bp)

    # 5. Diagnostic & Initialization Endpoints
    @app.route('/api/health')
    def health_check():
        model_ready = prediction_service.model is not None and prediction_service.vectorizer is not None
        return jsonify({
            "status": "healthy",
            "model_ready": model_ready,
            "database_configured": is_database_configured(),
            "serverless": is_vercel
        })

    @app.route('/api/init-db', methods=['GET', 'POST'])
    def trigger_init_db():
        """Allows one-click database schema creation from web in cloud deployments."""
        try:
            init_db()
            return jsonify({
                "success": True,
                "message": "Database schema and default demo accounts initialized successfully."
            })
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"Database initialization failed: {str(e)}"
            }), 500

    # 6. Error Handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('base.html', not_found=True), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('base.html', server_error=True), 500

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV', 'development') == 'development'
    print("==================================================")
    print("  SpamShield AI - Email Spam Detection Engine     ")
    print(f"  Server running on http://127.0.0.1:{port}        ")
    print("==================================================")
    app.run(host='0.0.0.0', port=port, debug=debug)
