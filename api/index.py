# Vercel entry point for FastAPI application
import sys
import os

# Add the parent directory to the path so we can import main
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app

# Export the app for Vercel
handler = app
