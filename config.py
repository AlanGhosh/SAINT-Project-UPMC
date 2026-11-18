import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_MAPS_KEY = os.getenv("GOOGLE_MAPS_KEY")
ORS_API_KEY = os.getenv("ORS_API_KEY")

if not GOOGLE_MAPS_KEY:
    raise ValueError("GOOGLE_MAPS_KEY not found in environment. Check your .env file.")
if not ORS_API_KEY:
    raise ValueError("ORS_API_KEY not found in environment. Check your .env file.")