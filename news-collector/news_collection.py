# news_collection.py - Minimal startup version
from flask import Flask, request, jsonify
import os
import sys
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

print("=== STARTING NEWS COLLECTOR ===", flush=True)
logger.info("Starting news collector service")

app = Flask(__name__)

@app.route('/', methods=['GET'])
def health_check():
    logger.info("Health check endpoint called")
    print("Health check called", flush=True)
    return 'News collector service is running - Minimal version'

@app.route('/test', methods=['GET'])
def test_endpoint():
    """Test endpoint to check basic functionality"""
    try:
        print("=== TEST ENDPOINT CALLED ===", flush=True)
        logger.info("Test endpoint called")
        
        api_key = os.getenv('EVENT_REGISTRY_API_KEY')
        database_url = os.getenv('DATABASE_URL')
        
        result = {
            "status": "ok",
            "api_key_present": bool(api_key),
            "api_key_length": len(api_key) if api_key else 0,
            "database_url_present": bool(database_url),
            "environment_variables": dict(os.environ),
            "python_version": sys.version
        }
        
        print(f"Test result: {result}", flush=True)
        return jsonify(result)
        
    except Exception as e:
        error_msg = f"Test endpoint error: {str(e)}"
        logger.error(error_msg)
        print(f"ERROR in test endpoint: {str(e)}", flush=True)
        return jsonify({"error": error_msg}), 500

@app.route('/trigger', methods=['GET', 'POST'])
def trigger_collection():
    """Placeholder trigger endpoint"""
    try:
        print("=== TRIGGER ENDPOINT CALLED ===", flush=True)
        logger.info("Trigger endpoint called")
        return 'Trigger endpoint working - news collection not implemented yet', 200
    except Exception as e:
        error_msg = f"Error in trigger endpoint: {str(e)}"
        logger.error(error_msg)
        print(f"ERROR: {error_msg}", flush=True)
        return f'Error: {str(e)}', 500

if __name__ == "__main__":
    print("=== STARTING FLASK SERVER ===", flush=True)
    logger.info("Starting Flask server")
    
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Flask server on port {port}", flush=True)
    logger.info(f"Starting Flask server on port {port}")
    
    try:
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        print(f"ERROR starting Flask server: {str(e)}", flush=True)
        logger.error(f"Error starting Flask server: {str(e)}")
        sys.exit(1)