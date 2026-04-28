# Smart Lead Generator

Streamlit app that uses Gemini to suggest high-demand areas, Google Places to find businesses, and OpenPyXL to download leads as an Excel file.

## Run locally

```powershell
pip install -r requirements.txt
python -m streamlit run app.py
```

## Local secrets

Create `.streamlit/secrets.toml`:

```toml
GOOGLE_API_KEY = "your_google_places_api_key"
GEMINI_API_KEY = "your_gemini_api_key"
```

## Deploy on Streamlit Community Cloud

1. Push this folder to a GitHub repository.
2. Go to Streamlit Community Cloud and create a new app.
3. Select the repository, branch, and `app.py` as the main file.
4. Add these secrets in the app's Secrets settings:

```toml
GOOGLE_API_KEY = "your_google_places_api_key"
GEMINI_API_KEY = "your_gemini_api_key"
```

5. Deploy the app.

Do not commit `.streamlit/secrets.toml`; it is already ignored by `.gitignore`.
