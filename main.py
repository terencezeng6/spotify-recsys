import requests
import os
from flask import Flask, redirect, request, jsonify, session, render_template
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
RECCOBEATS_BASE_URL = "https://api.reccobeats.com/v1/"

@app.route("/")
def index():
  logged_in = "access_token" in session and datetime.now().timestamp() < session["expires_at"]
  username = session.get("username", "Unknown User") if logged_in else None
  return render_template("index.html", logged_in=logged_in, username=username)


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
  playlists_json = response.json()

  playlists = []
  for playlist in playlists_json.get("items", []):
    name = playlist.get("name", "Unnamed Playlist")
    count = playlist.get("tracks", {}).get("total", 0)
    playlists.append({"name": name, "count": count})

  return render_template("playlists.html", playlists=playlists)


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
    "limit": 10,                # number of tracks to fetch; this takes a while, so decrease this as needed!
    "time_range": "long_term"   # data for ≈ past year; unfortunately, that's the longest range Spotify offers :(
  }
  response = requests.get(API_BASE_URL + "me/top/tracks", headers=headers, params=params)
  tracks_json = response.json()

  if "items" not in tracks_json:
    return "<p>Error fetching top tracks</p>"
  
  tracks = []
  for track in tracks_json["items"]:
    name = track.get("name", "Unknown track")
    artist = ", ".join([a["name"] for a in track.get("artists", [])])
    spotify_id = track.get("id")

    headers = {
      "Accept": "application/json"
    }
    params = {
      "ids": spotify_id
    }
    response = requests.get(RECCOBEATS_BASE_URL + "track", headers=headers, params=params)
    reccobeats = response.json()

    if "content" in reccobeats and len(reccobeats["content"]) > 0:
      reccobeats_id = reccobeats["content"][0]["id"]

      response = requests.get(RECCOBEATS_BASE_URL + f"track/{reccobeats_id}/audio-features", headers=headers)
      features = response.json()

      tracks.append({
        "name": name,
        "artist": artist,
        "acousticness": features.get("acousticness"),
        "danceability": features.get("danceability"),
        "energy": features.get("energy"),
        "instrumentalness": features.get("instrumentalness"),
        "loudness": features.get("loudness"),
        "valence": features.get("valence"),
        "available": True
      })
      
    else:
      tracks.append({
        "name": name,
        "artist": artist,
        "available": False
      })

  return render_template("top_tracks.html", tracks=tracks)

  
if __name__ == "__main__":
  app.run(host="0.0.0.0", debug=True)