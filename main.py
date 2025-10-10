import requests
import os
from flask import Flask, redirect, request, jsonify, session, render_template
import urllib.parse
from datetime import datetime
import concurrent.futures
import json
from requests.adapters import HTTPAdapter
from flask import Response, stream_with_context

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

  # check for optional time_range query param (short_term, medium_term, long_term)
  selected_range = request.args.get("time_range")

  valid_ranges = {"short_term", "medium_term", "long_term"}
  tracks_json = None

  if selected_range in valid_ranges:
    params = {
      "limit": 50,                # number of tracks to fetch; this takes a while, so decrease this as needed!
      "time_range": selected_range
    }
    response = requests.get(API_BASE_URL + "me/top/tracks", headers=headers, params=params)
    tracks_json = response.json()

    if "items" not in tracks_json:
      return "<p>Error fetching top tracks</p>"

  results = None
  if tracks_json:
    items = tracks_json.get("items", [])

    # reuse a Session with a connection pool to speed up many HTTP requests
    sess = requests.Session()
    sess.headers.update({"Accept": "application/json"})
    sess.mount('https://', HTTPAdapter(pool_connections=50, pool_maxsize=50))

    def fetch_reccobeats_data_with_sess(track):
      name = track.get("name", "Unknown track")
      artist = ", ".join([a["name"] for a in track.get("artists", [])])
      spotify_id = track.get("id")

      try:
        params = {"ids": spotify_id}
        response = sess.get(RECCOBEATS_BASE_URL + "track", params=params)
        if response.status_code != 200:
          print(f"Reccobeats track lookup HTTP {response.status_code} for spotify_id={spotify_id}: {response.text[:200]}")
          return {"name": name, "artist": artist, "available": False}

        reccobeats = response.json()

        if "content" in reccobeats and len(reccobeats["content"]) > 0:
          reccobeats_id = reccobeats["content"][0]["id"]
          response = sess.get(RECCOBEATS_BASE_URL + f"track/{reccobeats_id}/audio-features")

          features = response.json()
          return {
            "name": name,
            "artist": artist,
            "acousticness": features.get("acousticness"),
            "danceability": features.get("danceability"),
            "energy": features.get("energy"),
            "instrumentalness": features.get("instrumentalness"),
            "loudness": features.get("loudness"),
            "valence": features.get("valence"),
            "available": True
          }
      except Exception as e:
        print(f"Exception during Reccobeats lookup for spotify_id={spotify_id}: {e}")

      return {"name": name, "artist": artist, "available": False}

    max_workers = min(25, len(items))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
      results = list(executor.map(fetch_reccobeats_data_with_sess, items))

  # render the template with either None (no selection yet) or the fetched results
  return render_template("top_tracks.html", tracks=results, selected_range=selected_range)


@app.route('/top-tracks-stream')
def top_tracks_stream():
  # Server-Sent Events endpoint that streams progress and track data
  if "access_token" not in session:
    return ("Not authenticated", 401)

  if datetime.now().timestamp() > session["expires_at"]:
    return ("Token expired", 401)

  selected_range = request.args.get('time_range')
  valid_ranges = {"short_term", "medium_term", "long_term"}
  if selected_range not in valid_ranges:
    return ("Invalid time_range", 400)

  headers = {"Authorization": f"Bearer {session['access_token']}"}
  params = {"limit": 50, "time_range": selected_range}
  response = requests.get(API_BASE_URL + "me/top/tracks", headers=headers, params=params)
  tracks_json = response.json()
  if "items" not in tracks_json:
    return ("Error fetching top tracks", 500)

  items = tracks_json["items"]
  total = len(items)

  # use a requests.Session with connection pooling
  sess = requests.Session()
  sess.headers.update({"Accept": "application/json"})
  sess.mount('https://', HTTPAdapter(pool_connections=100, pool_maxsize=100))

  def fetch_reccobeats_data(track):
    name = track.get("name", "Unknown track")
    artist = ", ".join([a["name"] for a in track.get("artists", [])])
    spotify_id = track.get("id")

    try:
      params_rb = {"ids": spotify_id}
      response_rb = sess.get(RECCOBEATS_BASE_URL + "track", params=params_rb)
      if response_rb.status_code != 200:
        print(f"Reccobeats track lookup HTTP {response_rb.status_code} for spotify_id={spotify_id}: {response_rb.text[:200]}")
        return {"name": name, "artist": artist, "available": False}

      reccobeats = response_rb.json()

      if "content" in reccobeats and len(reccobeats["content"]) > 0:
        reccobeats_id = reccobeats["content"][0]["id"]
        response_feats = sess.get(RECCOBEATS_BASE_URL + f"track/{reccobeats_id}/audio-features")
        if response_feats.status_code != 200:
          print(f"Reccobeats audio-features HTTP {response_feats.status_code} for reccobeats_id={reccobeats_id}: {response_feats.text[:200]}")
          return {"name": name, "artist": artist, "available": False}

        features = response_feats.json()
        return {
          "name": name,
          "artist": artist,
          "acousticness": features.get("acousticness"),
          "danceability": features.get("danceability"),
          "energy": features.get("energy"),
          "instrumentalness": features.get("instrumentalness"),
          "loudness": features.get("loudness"),
          "valence": features.get("valence"),
          "available": True
        }
    except Exception as e:
      print(f"Exception during Reccobeats lookup for spotify_id={spotify_id}: {e}")

    return {"name": name, "artist": artist, "available": False}

  # we will fetch concurrently and yield results as they complete to provide smoother progress
  def generate():
    max_workers = min(32, max(4, total))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
      # schedule futures
      futures = [executor.submit(fetch_reccobeats_data, t) for t in items]

      # initial total message
      yield f"event: total\ndata: {json.dumps({'total': total})}\n\n"

      loaded = 0
      # map futures back to their original index so we can emit in-order
      fut_to_idx = {fut: idx for idx, fut in enumerate(futures)}
      results_buffer = {}
      next_to_emit = 0

      for fut in concurrent.futures.as_completed(futures):
        idx = fut_to_idx.get(fut)
        try:
          data = fut.result()
        except Exception:
          data = {"name": "Unknown", "artist": "", "available": False}

        loaded += 1
        # always send progress as tasks complete
        yield f"event: progress\ndata: {json.dumps({'loaded': loaded, 'total': total})}\n\n"

        # buffer the result and emit any ready results in order
        results_buffer[idx] = data
        while next_to_emit in results_buffer:
          out = results_buffer.pop(next_to_emit)
          yield f"event: track\ndata: {json.dumps(out)}\n\n"
          next_to_emit += 1

      # signal completion
      yield f"event: done\ndata: {{}}\n\n"

  return Response(stream_with_context(generate()), mimetype='text/event-stream')

  
if __name__ == "__main__":
  app.run(host="0.0.0.0", debug=True)