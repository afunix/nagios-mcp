import json
import time
from typing import Dict, Optional

import requests

NAGIOS_URL = None
NAGIOS_USER = None
CA_CERT_PATH = None
cgi_url = None
session = None
common_format_options = "whitespace enumerate bitmask duration"

# OAuth2 params
OAUTH_TOKEN_URL = None
OAUTH_CLIENT_ID = None
OAUTH_CLIENT_SECRET = None
OAUTH_USERNAME = None
OAUTH_PASSWORD = None

# Token cache
_token_value = None
_token_expires_at = 0.0
_TOKEN_REFRESH_BUFFER = 30  # seconds before expiry to proactively refresh


def _fetch_token() -> None:
    global _token_value, _token_expires_at

    payload = {
        "grant_type": "password",
        "client_id": OAUTH_CLIENT_ID,
        "client_secret": OAUTH_CLIENT_SECRET,
        "username": OAUTH_USERNAME,
        "password": OAUTH_PASSWORD,
    }
    verify = CA_CERT_PATH if CA_CERT_PATH else False

    try:
        response = requests.post(OAUTH_TOKEN_URL, data=payload, verify=verify, timeout=15)
        response.raise_for_status()
        token_data = response.json()
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(
            f"OAuth2 token request failed: HTTP {e.response.status_code} "
            f"from {OAUTH_TOKEN_URL}. Response: {e.response.text}"
        ) from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"OAuth2 token request failed: {e}") from e

    access_token = token_data.get("access_token")
    if not access_token:
        raise RuntimeError(
            f"OAuth2 response missing 'access_token'. Keys: {list(token_data.keys())}"
        )

    expires_in = token_data.get("expires_in")
    _token_value = access_token
    _token_expires_at = (
        time.time() + float(expires_in)
        if isinstance(expires_in, (int, float)) and expires_in > 0
        else time.time() + 300.0  # default 5 min if Keycloak omits expires_in
    )


def _get_valid_token() -> str:
    if _token_value is None or time.time() >= (_token_expires_at - _TOKEN_REFRESH_BUFFER):
        _fetch_token()
    return _token_value


def initialize_nagios_config(
    nagios_url: str,
    nagios_user: str,
    nagios_pass: str,
    client_id: str,
    client_secret: str,
    oauth_token_url: str,
    ca_cert_path: Optional[str] = None,
):
    """Initialize Nagios Configuration from provided parameters"""
    global NAGIOS_URL, NAGIOS_USER, CA_CERT_PATH, cgi_url, session
    global OAUTH_TOKEN_URL, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET
    global OAUTH_USERNAME, OAUTH_PASSWORD, _token_value, _token_expires_at

    NAGIOS_URL = nagios_url
    NAGIOS_USER = nagios_user
    CA_CERT_PATH = ca_cert_path
    OAUTH_TOKEN_URL = oauth_token_url
    OAUTH_CLIENT_ID = client_id
    OAUTH_CLIENT_SECRET = client_secret
    OAUTH_USERNAME = nagios_user
    OAUTH_PASSWORD = nagios_pass

    cgi_url = (
        f"{NAGIOS_URL}cgi-bin/"
        if NAGIOS_URL.endswith("/")
        else f"{NAGIOS_URL}/cgi-bin/"
    )

    session = requests.Session()
    if NAGIOS_URL.startswith("https://"):
        session.verify = ca_cert_path if ca_cert_path else False
    else:
        session.verify = False

    # Reset token cache; eagerly fetch first token to validate credentials at startup
    _token_value = None
    _token_expires_at = 0.0
    _fetch_token()


def _check_config():
    """Check if configuration has been initialized"""
    if NAGIOS_URL is None or NAGIOS_USER is None or OAUTH_TOKEN_URL is None:
        raise RuntimeError(
            "Nagios configuration not initialized. "
            "Make sure to run the server with a valid config file."
        )


def make_request(cgi_script: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """
    Helper function to make requests to Nagios Core CGI
    """
    _check_config()
    if params is None:
        params = {}

    if "details" not in params and cgi_script in ("statusjson.cgi", "objectjson.cgi"):
        if params.get("query", "").endswith("list"):
            params["details"] = "true"

    url = f"{cgi_url}{cgi_script}"

    def _do_request() -> requests.Response:
        headers = {"Authorization": f"Bearer {_get_valid_token()}"}
        return session.get(url, params=params, headers=headers, timeout=15)

    try:
        response = _do_request()
        if response.status_code == 401:
            _fetch_token()  # force refresh, bypassing cache
            response = _do_request()
        response.raise_for_status()

        response_json = response.json()
        if response_json.get("result", {}).get("type_code") == 0:
            return response_json.get("data", {})
        else:
            error_message = response_json.get("result", {}).get("message", "Unknown CGI Error")
            print(
                f"CGI Error for {cgi_script} with query '{params.get('query')}': {error_message}"
            )
            print(f"Full response for debug: {json.dumps(response_json, indent=2)}")
            return None
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e.response.status_code} for URL: {e.response.url}")
        print(f"Response Text: {e.response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Request Failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"Response text (if available): {e.response.text}")
    except json.JSONDecodeError as e:
        print(f"Failed to decode JSON: {e}")
    return None
