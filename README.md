# Webhook Application

FastAPI application with WhatsApp integration, Google Calendar, and database management.

## Features

- WhatsApp messaging integration
- Google Calendar event management
- Candidate management system
- Audio file handling
- Database operations with PostgreSQL
- Cloudinary integration for file storage
- **Privacy Policy static page** - `/public/privacy-policy/`

## Quick Start

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up environment variables (create a `.env` file):
```
OPENAI_API_KEY=your_key
WHATSAPP_TOKEN=your_token
WHATSAPP_PHONE_ID=your_phone_id
VERIFY_TOKEN=your_verify_token
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_secret
GOOGLE_CREDENTIALS_JSON=your_credentials
CALENDAR_ID=your_calendar_id
```

3. Run the application:
```bash
uvicorn main:app --reload
```

4. Access the API documentation:
```
http://localhost:8000/docs
```

## Privacy Policy

The privacy policy page is available at:
- Local: `http://localhost:8000/public/privacy-policy/`
- Production: `https://your-domain.vercel.app/public/privacy-policy/`

## Deployment

For detailed deployment instructions to Vercel, see [DEPLOYMENT.md](DEPLOYMENT.md).

### Quick Deploy to Vercel

1. Install Vercel CLI: `npm i -g vercel`
2. Login: `vercel login`
3. Deploy: `vercel --prod`

## Project Structure

- `main.py` - Main FastAPI application
- `public/privacy-policy/` - Static privacy policy page
- `audios/` - Audio files storage
- `requirements.txt` - Python dependencies
- `vercel.json` - Vercel deployment configuration

## License

All rights reserved © 2025
