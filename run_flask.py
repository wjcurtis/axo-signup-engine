#!/usr/bin/env python3
"""
Production Flask launcher for Replit deployment.
Implements keep-alive and proper SPA routing.
"""

import os
import sys
import time
import signal
import logging
from main import app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('flask.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class FlaskServer:
    def __init__(self):
        self.running = True
        self.port = int(os.environ.get("PORT", "8080"))
        
    def signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
        
    def start_server(self):
        """Start Flask server with keep-alive mechanism"""
        # Register signal handlers
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        
        logger.info(f"🚀 Starting AXO Flask SPA on 0.0.0.0:{self.port}")
        logger.info(f"🌐 Public URL: https://axo-referral-engine.onrender.com")
        
        retry_count = 0
        max_retries = 10
        
        while self.running and retry_count < max_retries:
            try:
                logger.info(f"Flask server attempt {retry_count + 1}")
                
                # Configure Flask for production
                app.config['ENV'] = 'production'
                app.config['DEBUG'] = False
                app.config['TESTING'] = False
                
                # Start server
                app.run(
                    host="0.0.0.0",
                    port=self.port,
                    debug=False,
                    use_reloader=False,
                    threaded=True
                )
                
            except Exception as e:
                retry_count += 1
                logger.error(f"Server error: {e}")
                if retry_count < max_retries:
                    logger.info(f"Retrying in 5 seconds... ({retry_count}/{max_retries})")
                    time.sleep(5)
                else:
                    logger.error("Max retries reached, exiting")
                    break
                    
        logger.info("Flask server shutdown complete")

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 8080))

    logger.info(f"🚀 Starting AXO Flask SPA on 0.0.0.0:{port}")



    # Print your Render public URL

    public_url = "https://axo-referral-engine.onrender.com"

    print(f"🌐 Public URL: {public_url}")

    logger.info(f"🌐 Public URL: {public_url}")



    app.run(host="0.0.0.0", port=port)