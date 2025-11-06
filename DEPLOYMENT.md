# Deployment Guide - Privacy Policy Page

## Overview
This repository includes a static privacy policy page that can be deployed to Vercel along with the FastAPI application.

## What's Been Added

### 1. Privacy Policy Page
- Location: `public/privacy-policy/index.html`
- A fully responsive, static HTML page with privacy policy content in Spanish
- Professional styling with modern CSS
- Mobile-friendly design

### 2. Static Files Configuration
The `main.py` file has been updated to serve static files from the `public` directory:
```python
PUBLIC_DIR = "public"
os.makedirs(PUBLIC_DIR, exist_ok=True)
app.mount("/public", StaticFiles(directory=PUBLIC_DIR, html=True), name="public")

# Direct endpoint for privacy policy
@app.get("/privacy-policy/")
async def get_privacy_policy():
    """Sirve la página de política de privacidad"""
    privacy_policy_path = os.path.join(PUBLIC_DIR, "privacy-policy", "index.html")
    if os.path.exists(privacy_policy_path):
        return FileResponse(privacy_policy_path, media_type="text/html")
    raise HTTPException(status_code=404, detail="Privacy policy page not found")
```

### 3. Vercel Configuration
A `vercel.json` file has been created to configure the Vercel deployment:
```json
{
  "version": 2,
  "builds": [
    {
      "src": "api/index.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/(.*)",
      "dest": "api/index.py"
    }
  ]
}
```

### 4. Vercel Entry Point
An `api/index.py` file has been created as the Vercel entry point:
```python
# Vercel entry point for FastAPI application
import sys
import os

# Add the parent directory to the path so we can import main
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app

# Export the app for Vercel
handler = app
```

This structure follows Vercel's recommended pattern for Python applications. All routing is handled by the FastAPI application, which serves both the API endpoints and static files.

## Deploying to Vercel

### Option 1: Vercel CLI

1. Install Vercel CLI:
```bash
npm i -g vercel
```

2. Login to Vercel:
```bash
vercel login
```

3. Deploy from the project root:
```bash
vercel
```

4. For production deployment:
```bash
vercel --prod
```

### Option 2: Vercel Dashboard (Recommended)

1. Go to [vercel.com](https://vercel.com) and sign in
2. Click "Add New Project"
3. Import your Git repository (GitHub/GitLab/Bitbucket)
4. Vercel will automatically detect the `vercel.json` configuration
5. Configure environment variables if needed:
   - `OPENAI_API_KEY`
   - `WHATSAPP_TOKEN`
   - `WHATSAPP_PHONE_ID`
   - `VERIFY_TOKEN`
   - `CLOUDINARY_CLOUD_NAME`
   - `CLOUDINARY_API_KEY`
   - `CLOUDINARY_API_SECRET`
   - `GOOGLE_CREDENTIALS_JSON`
   - `CALENDAR_ID`
   - Any other environment variables from `.env`
6. Click "Deploy"

### Option 3: GitHub Integration

1. Connect your GitHub repository to Vercel
2. Enable automatic deployments
3. Every push to main branch will trigger a new deployment
4. Pull requests will get preview deployments

## Accessing the Privacy Policy Page

After deployment, the privacy policy page will be accessible at:
```
https://your-domain.vercel.app/privacy-policy/
```

Or via the mounted static files route:
```
https://your-domain.vercel.app/public/privacy-policy/
```

With custom domain (e.g., talentum-manager.com):
```
https://talentum-manager.com/privacy-policy/
```

## Local Testing

To test the application locally:

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file with your environment variables

3. Run the application:
```bash
uvicorn main:app --reload
```

4. Access the privacy policy at:
```
http://localhost:8000/privacy-policy/
```

Or:
```
http://localhost:8000/public/privacy-policy/
```

## Directory Structure

```
webhook/
├── api/
│   └── index.py                    # Vercel entry point
├── main.py                          # FastAPI application
├── vercel.json                      # Vercel deployment configuration
├── requirements.txt                 # Python dependencies
├── public/                          # Static files directory
│   └── privacy-policy/
│       └── index.html              # Privacy policy page
├── audios/                          # Audio files directory
└── ... (other application files)
```

## Important Notes

1. **Environment Variables**: Make sure all required environment variables are configured in Vercel dashboard
2. **Python Version**: Vercel uses Python 3.9+ by default
3. **Build Time**: First deployment may take a few minutes
4. **Static Files**: The `html=True` parameter in StaticFiles allows direct access to HTML files
5. **CORS**: CORS is configured to allow all origins in main.py

## Troubleshooting

### Deployment fails
- Check that all environment variables are set in Vercel
- Verify that `requirements.txt` has all dependencies
- Check Vercel build logs for specific errors

### Privacy policy page not loading
- Verify the URL includes `/public/privacy-policy/`
- Check that the public directory exists in the deployment
- Review Vercel function logs

### Static files not found
- Ensure `vercel.json` routes are configured correctly
- Check that the public directory is not in `.gitignore`
- Verify the mount path in `main.py`

## Support

For issues related to:
- Vercel deployment: Check [Vercel Documentation](https://vercel.com/docs)
- FastAPI: Check [FastAPI Documentation](https://fastapi.tiangolo.com/)
- This application: Open an issue in the repository
