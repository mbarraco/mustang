# mustang

## Google sign-in

The app now supports Google OAuth for both sign-in and first-time signup flows.

1. Create an OAuth 2.0 "Web application" client inside the Google Cloud Console.
2. Add `http://localhost:8000/accounts/google/login/callback/` (and the equivalent production URL) to the client's authorized redirect URIs.
3. Export the credentials before starting Django:

   ```bash
   export GOOGLE_OAUTH_CLIENT_ID="your-client-id.apps.googleusercontent.com"
   export GOOGLE_OAUTH_CLIENT_SECRET="your-client-secret"
   ```

4. Run the migrations so django-allauth's tables (including `django_site`) are created:

   ```bash
   python src/mustang/manage.py migrate
   ```

When both variables are present the login form will render a "Continue with Google"
button. Without them, the button stays hidden so local development still works
with traditional username/password accounts.

## Alpha Vantage API keys

The stock lookup views call Alpha Vantage's APIs. Provide at least one API key via
`ALPHAVANTAGE_API_KEY`. To reduce downtime when the daily limit is hit, you can also
set `ALPHAVANTAGE_SECONDARY_API_KEY` with a fallback key:

```bash
export ALPHAVANTAGE_API_KEY="primary-key"
export ALPHAVANTAGE_SECONDARY_API_KEY="secondary-key"
```

The application automatically retries Alpha Vantage requests with the secondary key
whenever the primary key responds with a rate-limit notice.
