import requests
import os
from dotenv import load_dotenv
from flask import Flask, redirect, request, jsonify, session, render_template
import urllib.parse
from datetime import datetime
import time

import aiohttp
import json
import asyncio

import math
import random
import numpy as np

from collections import defaultdict

app = Flask(__name__)
app.secret_key = "idk_what_this_is_for"

load_dotenv()

spotify_id = os.getenv("client_id")
spotify_secret = os.getenv("client_secret")
lastfm_id = os.getenv("lastfm_id")

REDIRECT_URI = os.getenv("redirect_uri")
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_BASE_URL = "https://api.spotify.com/v1/"
RECCOBEATS_BASE_URL = "https://api.reccobeats.com/v1/"
LASTFM_BASE_URL = "http://ws.audioscrobbler.com/2.0/"


@app.route("/rate", methods=["POST"])
def rate():
  # Accept JSON payload { rec_id, rec_type, rating, comment, song_name, song_artist, valence, energy }
  payload = {}
  if request.is_json:
    payload = request.get_json()
  else:
    payload = request.form.to_dict()

  rec_id = payload.get('rec_id', '')
  rec_type = payload.get('rec_type', '')
  rating = payload.get('rating')
  comment = payload.get('comment', '')
  
  # Get song metadata
  song_name = payload.get('song_name', '')
  song_artist = payload.get('song_artist', '')
  valence = payload.get('valence', '')
  energy = payload.get('energy', '')
  
  # Get context information
  mood = payload.get('mood', '')
  time_range = payload.get('time_range', '')

  try:
    rating_val = int(rating)
  except Exception:
    rating_val = None

  username = session.get('username', 'anonymous')
  ts = datetime.utcnow().isoformat() + 'Z'
  safe_comment = str(comment).replace('\n', ' ').replace('\r', ' ').strip()
  safe_name = str(song_name).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ').strip()
  safe_artist = str(song_artist).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ').strip()

  # Updated log format: timestamp, username, rec_type, rec_id, rating, comment, song_name, song_artist, valence, energy, mood, time_range
  line = f"{ts}\t{username}\t{rec_type}\t{rec_id}\t{rating_val}\t{safe_comment}\t{safe_name}\t{safe_artist}\t{valence}\t{energy}\t{mood}\t{time_range}\n"
  try:
    path = os.path.join(app.root_path, 'ratings.txt')
    with open(path, 'a', encoding='utf-8') as f:
      f.write(line)
    return jsonify({'ok': True})
  except Exception as e:
    return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/")
def index():
  logged_in = "access_token" in session and datetime.now().timestamp() < session["expires_at"]
  username = session.get("username", "Unknown User") if logged_in else None
  return render_template("index.html", logged_in=logged_in, username=username)


@app.route("/login")
def login():
  scope = "user-read-private user-top-read"

  params = {
    "client_id": spotify_id,
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
      "client_id": spotify_id,
      "client_secret": spotify_secret
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
      "client_id": spotify_id,
      "client_secret": spotify_secret
    }

    response = requests.post(TOKEN_URL, data=req_body)
    token_info = response.json()

    session["access_token"] = token_info["access_token"]
    session["refresh_token"] = token_info["refresh_token"]
    session["expires_at"] = datetime.now().timestamp() + token_info["expires_in"]

    # fetch user profile
    headers = {"Authorization": f"Bearer {session["access_token"]}"}
    user_response = requests.get(SPOTIFY_BASE_URL + "me", headers=headers)
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

  response = requests.get(SPOTIFY_BASE_URL + "me/playlists", headers=headers)
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
  
  time_range = request.args.get("time_range")  # Get the time_range from the query parameter
  mood = request.args.get("mood")
  if time_range not in ["short_term", "medium_term", "long_term"]:
      return render_template("top_tracks.html", tracks=None, selected_range=None, selected_mood=mood)
  
  
  headers = {
    "Authorization": f"Bearer {session["access_token"]}"
  }

  params = {
    "limit": 50,                # number of tracks to fetch; decrease this if slow
    "time_range": time_range    # use selected time_range
  }
  response = requests.get(SPOTIFY_BASE_URL + "me/top/tracks", headers=headers, params=params)
  tracks_json = response.json()

  if "items" not in tracks_json:  
    return "<p>Error fetching top tracks</p>"

  async def fetch_reccobeats_data(session, track):
    name = track.get("name", "Unknown track")
    artist = ", ".join([a["name"] for a in track.get("artists", [])])
    spotify_id = track.get("id")

    headers = {
      "Accept": "application/json"
    }
    params = {
      "ids": spotify_id
    }
    # robustly fetch Reccobeats track lookup with retries and tolerant JSON parsing
    reccobeats = None
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
      try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with session.get(RECCOBEATS_BASE_URL + "track", headers=headers, params=params, timeout=timeout) as response:
          if response.status != 200:
            # consume body for debugging then retry or break
            text = await response.text()
            print(f"RECCOBEATS lookup status={response.status}, attempt={attempt}, body={text[:200]}")
            reccobeats = {}
          else:
            try:
              reccobeats = await response.json()
            except (aiohttp.ClientPayloadError, aiohttp.ContentTypeError, json.JSONDecodeError) as e:
              # fallback: read text and try to parse leniently
              text = await response.text()
              try:
                reccobeats = json.loads(text)
              except Exception:
                print(f"Failed to parse Reccobeats JSON on attempt {attempt}: {e}; body={text[:200]}")
                reccobeats = {}
      except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionResetError) as e:
        print(f"Reccobeats request error (attempt {attempt}): {e}")
        reccobeats = {}
      if reccobeats:
        break
        # small backoff before retrying
        await asyncio.sleep(0.3 * attempt)

    if reccobeats and "content" in reccobeats and len(reccobeats["content"]) > 0:
      reccobeats_id = reccobeats["content"][0]["id"]

      # fetch audio features with same defensive approach
      features = {}
      for attempt in range(1, max_attempts + 1):
        try:
          timeout = aiohttp.ClientTimeout(total=10)
          async with session.get(RECCOBEATS_BASE_URL + f"track/{reccobeats_id}/audio-features", headers=headers, timeout=timeout) as response:
            if response.status != 200:
              text = await response.text()
              print(f"Reccobeats features status={response.status}, attempt={attempt}, body={text[:200]}")
            else:
              try:
                features = await response.json()
              except (aiohttp.ClientPayloadError, aiohttp.ContentTypeError, json.JSONDecodeError) as e:
                text = await response.text()
                try:
                  features = json.loads(text)
                except Exception:
                  print(f"Failed to parse features JSON on attempt {attempt}: {e}; body={text[:200]}")
                  features = {}
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionResetError) as e:
          print(f"Reccobeats features request error (attempt {attempt}): {e}")
        if features:
          break
        await asyncio.sleep(0.3 * attempt)

      return {
        "name":             name,
        "artist":           artist,
        "spotify_id":       spotify_id,
        "rb_id":            reccobeats_id,
        "acousticness":     format(features.get("acousticness"), ".2f"),
        "danceability":     format(features.get("danceability"), ".2f"),
        "energy":           format(features.get("energy"), ".2f"),
        "instrumentalness": format(features.get("instrumentalness"), ".2f"),
        "loudness":         format(features.get("loudness"), ".2f"),
        "valence":          format(features.get("valence"), ".2f"),
        "available":        True
      }
      
    else:
      return {
        "name": name,
        "artist": artist,
        "energy": -1,
        "valence": -1,
        "available": False
      }
    
  async def fetch_all_reccobeats_data(tracks_json):
    async with aiohttp.ClientSession() as session:
      tasks = [
        fetch_reccobeats_data(session, track)
        for track in tracks_json["items"]
      ]
      results = await asyncio.gather(*tasks)
      return results

  tracks = asyncio.run(fetch_all_reccobeats_data(tracks_json))


  # randomly choose songs from available tracks and get some similar songs for each

  num_seeds = 15
  chosen_seeds = random.sample(range(len(tracks)), num_seeds)

  # print("SEEDS:")
  # for j, i in enumerate(chosen_seeds):
  #   print(f"{j}: {tracks[i]["name"]} by {tracks[i]["artist"]}")

  def get_tasks(session):
    tasks = []
    for i in chosen_seeds:
      track = tracks[i]

      params = {
        "method": "track.getsimilar",
        "artist": track["artist"].split(',')[0].strip(),  # split because API only takes one artist, not multiple
        "track": track["name"],     
        "api_key": lastfm_id,
        "limit": 1,
        "autocorrect": 2,
        "format": "json",
      }

      tasks.append(session.get(LASTFM_BASE_URL, params=params))
    return tasks

  results = []
  async def run_tasks():
    session = aiohttp.ClientSession()
    tasks = get_tasks(session)
    responses = await asyncio.gather(*tasks)
    for i, response in enumerate(responses):
      if response.status != 200:
        print(f"ERROR {response.status} on task {i}")
      results.append(await response.json())
    await session.close()

  asyncio.run(run_tasks())


  # index recommendations with only necessary info

  recs = defaultdict(dict)
  i = 0
  for result in results:
    if result == None:
      continue
    for track in result["similartracks"]["track"]:
      recs[i]["name"] = track["name"]
      recs[i]["artist"] = track.get("artist").get("name")
      i += 1

  print("RECS ORIGINAL:")
  for rec in recs.values():
    print(rec)


  # Use Spotify search endpoint to get Spotify ID from song name + artist (multithreaded)

  def get_tasks(multithread_session):
    tasks = []
    for track in recs.values():
      track_name = track["name"]
      artist_name = track["artist"]
      params = {
        "q": f"track:{track_name} artist:{artist_name}",
        "type": "track",
        "limit": 1,
      }
      headers = {
        "Authorization": f"Bearer {session["access_token"]}"
      }
      tasks.append(multithread_session.get(SPOTIFY_BASE_URL+"search", params=params, headers=headers))
    return tasks

  results = []
  async def run_tasks():
    multithread_session = aiohttp.ClientSession()
    tasks = get_tasks(multithread_session)
    responses = await asyncio.gather(*tasks)
    for response in responses:
      if response.status != 200:
        print(f"ERROR {response.status}")
      results.append(await response.json())
    await multithread_session.close()

  asyncio.run(run_tasks())  

  for i, rec in recs.items():
    rec["spotify_id"] = results[i]["tracks"]["items"][0]["id"]

  print("RECS WITH SPOTIFY IDS:")
  for i, rec in recs.items():
    print(i, rec)


  # Find Reccobeats IDs from Spotify IDs

  def get_tasks(multithread_session):
    tasks = []
    for track in recs.values():
      params = {
        "ids": [track["spotify_id"]]
      }
      headers = {
        'Accept': 'application/json'
      }
      tasks.append(multithread_session.get(RECCOBEATS_BASE_URL+"track", headers=headers, params=params))
    return tasks

  results = []
  async def run_tasks():
    multithread_session = aiohttp.ClientSession()
    tasks = get_tasks(multithread_session)
    responses = await asyncio.gather(*tasks)
    for response in responses:
      if response.status != 200:
        print(f"ERROR {response.status}")
      results.append(await response.json())
    await multithread_session.close()

  asyncio.run(run_tasks())

  for i, rec in recs.items():
    if "error" in results[i]:
      rec["rb_id"] = "None"
      continue
    if not results[i]["content"]:
      rec["rb_id"] = "None"
      continue
    else:
      rec["rb_id"] = results[i]["content"][0]["id"]

  print("RECS WITH RECCOBEATS IDS:")
  for i, rec in recs.items():
    print(i, rec)

  
  # Find valence-energy data for all songs that have Reccobeats ID

  # no multithreading, batch request (takes up to 40 tracks)

  # params = {
  #   "ids": [rec["rb_id"] for rec in recs.values()]
  # }
  # headers = {
  #   'Accept': 'application/json'
  # }
  # response = requests.get(RECCOBEATS_BASE_URL + "audio-features", headers=headers, params=params)
  # audio_features = response.json()

  # print("AUDIO_FEATURES OUTPUT:", audio_features)

  # for features in audio_features["content"]:
  #   for rec in recs.values():
  #     if rec["rb_id"] == features["id"]:
  #       rec["valence"] = features["valence"]
  #       rec["energy"] = features["energy"]

  # for rec in recs.values():
  #   if "valence" not in rec:
  #     rec["valence"] = -1
  #   if "energy" not in rec:
  #     rec["energy"] = -1

  # multithreaded version, single track per request

  def get_tasks(multithread_session):
    tasks = []
    for track in recs.values():
      rb_id = track["rb_id"]
      headers = {
        'Accept': 'application/json'
      }
      tasks.append(multithread_session.get(RECCOBEATS_BASE_URL+"track/"+rb_id+"/audio-features", headers=headers))
    return tasks

  results = []
  async def run_tasks():
    multithread_session = aiohttp.ClientSession()
    tasks = get_tasks(multithread_session)
    responses = await asyncio.gather(*tasks)
    for response in responses:
      if response.status != 200:
        print(f"ERROR {response.status}")
      results.append(await response.json())
    await multithread_session.close()

  asyncio.run(run_tasks())

  for i, rec in recs.items():
    if "error" in results[i]:
      rec["valence"] = -1
      rec["energy"] = -1
    else:
      rec["valence"] = results[i]["valence"]
      rec["energy"] = results[i]["energy"]
  
  
  print("RECS WITH VALENCE ENERGY:")
  for i, rec in recs.items():
    print(i, f"{rec["name"]} by {rec["artist"]}, {rec["valence"]}, {rec["energy"]}")


  # calculate probabilities

  user_mood = [0.5, 0.5]    # target [valence, energy]
  k = 0.02                  # decay factor

  if mood == "angry":
    user_mood = [0.1, 0.8]
  elif mood == "stimulated":
    user_mood = [0.5, 0.8]
  elif mood == "excited":
    user_mood = [0.8, 0.8]
  elif mood == "distressed":
    user_mood = [0.2, 0.5]
  elif mood == "neutral":
    user_mood = [0.5, 0.5]
  elif mood == "happy":
    user_mood = [0.8, 0.5]
  elif mood == "sad":
    user_mood = [0.2, 0.2]
  elif mood == "tired":
    user_mood = [0.5, 0.2]
  elif mood == "relaxed":
    user_mood = [0.8, 0.2]

  probabilities = [abs(float(rec["valence"]) - user_mood[0])**2 + abs(float(rec["energy"]) - user_mood[1])**2 for rec in recs.values()]
  probabilities = [math.exp(-x/k) for x in probabilities]
  probabilities = [x / sum(probabilities) for x in probabilities]
  print("PROBABILITIES:", probabilities)

  num_recommendations = 2
  vanilla_recommendations = random.sample(range(len(recs)), num_recommendations)
  print(vanilla_recommendations)
  print("Vanilla Recommendations:")
  for i in vanilla_recommendations:
    rec = recs[i]
    print(rec["name"], "by", rec["artist"])
    print("Valence:", rec["valence"], "Energy:", rec["energy"])
  print("")

  print("Biased Recommendations:")
  biased_recommendations = np.random.choice(len(recs), size=num_recommendations, p=probabilities, replace=False)
  print(biased_recommendations)
  for i in biased_recommendations:
    rec = recs[i]
    print(rec["name"], "by", rec["artist"])
    print("Valence:", rec["valence"], "Energy:", rec["energy"])

  vanilla_rec = recs[vanilla_recommendations[0]]["spotify_id"]
  biased_rec = recs[biased_recommendations[0]]["spotify_id"]

  # Track which index to use for metadata
  vanilla_idx = vanilla_recommendations[0]
  biased_idx = biased_recommendations[0]

  if vanilla_rec == biased_rec:
    vanilla_rec = recs[vanilla_recommendations[1]]["spotify_id"]
    vanilla_idx = vanilla_recommendations[1]

  # Create list with both recommendations including metadata
  recommendations = [
    {
      "spotify_id": vanilla_rec, 
      "rec_type": "vanilla",
      "name": recs[vanilla_idx]["name"],
      "artist": recs[vanilla_idx]["artist"],
      "valence": recs[vanilla_idx]["valence"],
      "energy": recs[vanilla_idx]["energy"]
    },
    {
      "spotify_id": biased_rec, 
      "rec_type": "biased",
      "name": recs[biased_idx]["name"],
      "artist": recs[biased_idx]["artist"],
      "valence": recs[biased_idx]["valence"],
      "energy": recs[biased_idx]["energy"]
    }
  ]

  # Add context (mood and time_range) to each recommendation
  for rec in recommendations:
    rec['mood'] = mood
    rec['time_range'] = time_range

  # Randomly shuffle the order
  random.shuffle(recommendations)

  return render_template(
    "top_tracks.html", 
    tracks=tracks, 
    selected_range=time_range, 
    selected_mood=mood,
    recommendations=recommendations
  )

  
if __name__ == "__main__":
  app.run(host="0.0.0.0", debug=True)