import requests
import os
from flask import Flask, redirect, request, jsonify, session
import urllib.parse
from datetime import datetime

app = Flask(__name__)
app.secret_key = "idk_what_this_is_for"

client_id = os.getenv("client_id")
client_secret = os.getenv("client_secret")

REDIRECT_URI = "http://127.0.0.1:5000/callback"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE_URL = "https://api.spotify.com/v1/"

@app.route("/")
def index():
  if "access_token" in session and datetime.now().timestamp() < session["expires_at"]:
    username = session.get("username", "Unknown User")
    return f"""
      <span>Logged in as {username}</span>
      <form action="/logout" method="get" style="display:inline;">
        <button type="submit">Log Out</button>
      </form>
      <br><br>
      <form action="/playlists" method="get">
        <button type="submit">See Playlists</button>
      </form>
      <form action="/top-tracks" method="get">
        <button type="submit">See Top Tracks</button>
      </form>
    """
  return f"""
    <form action="/login" method="get">
      <button type="submit">Login with Spotify</button>
    </form>
  """


@app.route("/login")
def login():
  scope = "user-read-private user-read-email user-top-read"

  params = {
    "client_id": client_id,
    "response_type": "code",
    "scope": scope,
    "redirect_uri": REDIRECT_URI,
    "show_dialog": True     # set this to false to avoid login time limit
  }

  auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

  return redirect(auth_url)


@app.route("/logout")
def logout():
  session.clear()
  return redirect("/")


@app.route("/refresh-token")
def refresh_token():
  if "refresh_token" not in session:
    return redirect("/login")
  
  if datetime.now().timestamp() > session["expires_at"]:
    req_body = {
      "grant_type": "refresh_token",
      "refresh_token": session["refresh_token"],
      "client_id": client_id,
      "client_secret": client_secret
    }

    response = requests.post(TOKEN_URL, data=req_body)
    new_token_info = response.json()

    session["access_token"] = new_token_info["access_token"]
    session["expires_at"] = datetime.now().timestamp() + new_token_info["expires_in"]

    return redirect("/playlists")


@app.route("/callback")
def callback():
  if "error" in request.args:
    return jsonify({"error": request.args["error"]})
  
  if "code" in request.args:
    req_body = {
      "code": request.args["code"],
      "grant_type": "authorization_code",
      "redirect_uri": REDIRECT_URI,
      "client_id": client_id,
      "client_secret": client_secret
    }

    response = requests.post(TOKEN_URL, data=req_body)
    token_info = response.json()

    session["access_token"] = token_info["access_token"]
    session["refresh_token"] = token_info["refresh_token"]
    session["expires_at"] = datetime.now().timestamp() + token_info["expires_in"]

    # fetch user profile
    headers = {"Authorization": f"Bearer {session["access_token"]}"}
    user_response = requests.get(API_BASE_URL + "me", headers=headers)
    user_info = user_response.json()
    session["username"] = user_info.get("display_name", "Unknown User")

    return redirect('/')
  

@app.route("/playlists")
def get_playlists():
  if "access_token" not in session:
    return redirect("/login")

  if datetime.now().timestamp() > session["expires_at"]:
    return redirect("/refresh-token")
  
  headers = {
    "Authorization": f"Bearer {session["access_token"]}"
  }

  response = requests.get(API_BASE_URL + "me/playlists", headers=headers)
  playlists = response.json()

  output = """
      <form action="/" method="get">
        <button type="submit">Back to Main Page</button>
      </form>
    """
  output += "<h2>Playlists:</h2><ul>"
  for playlist in playlists["items"]:
    name = playlist.get("name", "Unnamed Playlist")
    count = playlist.get("tracks", {}).get("total", 0)
    output += f"<li>{name}: {count} tracks</li>"
  output += "</ul>"

  return output


@app.route("/top-tracks")
def top_tracks():
  if "access_token" not in session:
    return redirect("/login")

  if datetime.now().timestamp() > session["expires_at"]:
    return redirect("/refresh-token")
  
  headers = {
    "Authorization": f"Bearer {session["access_token"]}"
  }

  params = {
    "limit": 50,
    "time_range": "long_term"
  }
  response = requests.get(API_BASE_URL + "me/top/tracks", headers=headers, params=params)
  tracks = response.json()

  if "items" not in tracks:
    return "<p>Error fetching top tracks</p>"
  
  output = """
      <form action="/" method="get">
        <button type="submit">Back to Main Page</button>
      </form>
    """
  output += "<h2> Most played tracks in the past year</h2><ol>"
  for track in tracks["items"]:
    name = track.get("name", "Unknown track")
    artist = ", ".join([a["name"] for a in track.get("artists", [])])

    output += f"""
      <li>
        {name} — {artist}
      </li>
    """  

  output += "</ol>"

  return output

  
if __name__ == "__main__":
  app.run(host="0.0.0.0", debug=True)