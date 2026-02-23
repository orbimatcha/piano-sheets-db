from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
import re
from github import Github
from datetime import datetime
import base64

app = Flask(__name__)
CORS(app)

# GitHub Configuration
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'orb1ispare/piano-sheets-db')
GITHUB_BRANCH = 'main'
SHEETS_FILE_PATH = 'sheets/piano_sheets.json'
FAVORITES_FILE_PATH = 'users/data.js'

# Initialize GitHub client
g = Github(GITHUB_TOKEN) if GITHUB_TOKEN else None
repo = g.get_repo(GITHUB_REPO) if g else None

def get_songs_data():
    """Get songs data from GitHub - FIXED for large files"""
    try:
        if not repo:
            print("ERROR: GitHub not configured - GITHUB_TOKEN missing")
            return None, "GitHub not configured - check GITHUB_TOKEN environment variable"
        
        print(f"Fetching songs from: {GITHUB_REPO}/{SHEETS_FILE_PATH}")
        
        # FIX: Use raw content URL for large files
        try:
            file = repo.get_contents(SHEETS_FILE_PATH, ref=GITHUB_BRANCH)
            
            # Check if encoding is 'none' (file too large)
            if file.encoding == 'none':
                print("  → File too large, using download_url instead")
                import requests
                response = requests.get(file.download_url)
                content = response.text
            else:
                # Normal decoding for smaller files
                content = file.decoded_content.decode()
            
            songs = json.loads(content)
            print(f"  ✓ Successfully loaded {len(songs)} songs!")
            return songs, None
            
        except AssertionError as ae:
            # Fallback: direct raw URL
            print(f"  → AssertionError, using raw URL: {str(ae)}")
            raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{SHEETS_FILE_PATH}"
            import requests
            response = requests.get(raw_url)
            songs = json.loads(response.text)
            print(f"  ✓ Loaded {len(songs)} songs via raw URL!")
            return songs, None
            
    except Exception as e:
        print(f"ERROR in get_songs_data: {str(e)}")
        import traceback
        traceback.print_exc()
        return None, str(e)

def get_all_favorites():
    """Get all users' favorites from data.js"""
    try:
        if not repo:
            return {}, "GitHub not configured"
        
        file = repo.get_contents(FAVORITES_FILE_PATH, ref=GITHUB_BRANCH)
        
        # Handle large files
        if file.encoding == 'none':
            import requests
            content = requests.get(file.download_url).text
        else:
            content = file.decoded_content.decode()
        
        # Parse JavaScript object
        match = re.search(r'favorites\s*=\s*({[\s\S]*?});', content)
        if match:
            json_str = match.group(1)
            # Remove comments
            json_str = re.sub(r'//.*?\n', '', json_str)
            # Replace single quotes with double quotes
            json_str = json_str.replace("'", '"')
            # Remove trailing commas before closing braces
            json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
            
            try:
                favorites = json.loads(json_str)
                return favorites, None
            except json.JSONDecodeError as e:
                print(f"JSON Parse Error: {e}")
                print(f"Problematic JSON: {json_str[:200]}")
                return {}, None
        return {}, None
    except Exception as e:
        return {}, str(e)

def get_user_favorites(user_id):
    """Get specific user's favorites"""
    all_favs, error = get_all_favorites()
    if error:
        return [], error
    return all_favs.get(user_id, []), None

def update_user_favorites(user_id, favorites_list):
    """Update specific user's favorites in data.js"""
    try:
        if not repo:
            return False, "GitHub not configured"
        
        file = repo.get_contents(FAVORITES_FILE_PATH, ref=GITHUB_BRANCH)
        
        all_favs, error = get_all_favorites()
        if error and "not configured" in error:
            return False, error
        
        all_favs[user_id] = favorites_list
        
        # Convert to JavaScript format
        js_content = "export const favorites = {\n"
        for uid, favs in all_favs.items():
            songs_str = ', '.join([f'"{song}"' for song in favs])
            js_content += f'  "{uid}": [{songs_str}],\n'
        js_content = js_content.rstrip(',\n') + '\n};\n'
        
        new_content = f"""// Auto-generated favorites list
// Multi-user support - each user has their own favorites
// Updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

{js_content}"""
        
        repo.update_file(
            FAVORITES_FILE_PATH,
            f"Update favorites for user {user_id}",
            new_content,
            file.sha,
            branch=GITHUB_BRANCH
        )
        
        return True, None
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    return jsonify({
        'status': 'online',
        'name': 'Matcha Piano Sheets API',
        'version': '2.2.0',
        'description': 'Multi-user API for Matcha Piano Player - GET/POST Support',
        'source': 'https://github.com/AlfaLuaTest/piano-sheets-db',
        'endpoints': {
            'GET /': 'API information',
            'GET /api/songs': 'Get all songs (simplified)',
            'GET /api/songs/full': 'Get all songs with sheet music',
            'GET /api/song/<id>': 'Get specific song by ID',
            'GET /api/search?q=query': 'Search songs by title or artist',
            'GET /api/categories': 'Get all available categories',
            'GET /api/category/<name>': 'Get songs by category',
            'GET /api/stats': 'Get database statistics',
            'GET /api/random': 'Get a random song',
            'GET /api/favorites/<user_id>': 'Get user favorites',
            'GET/POST /api/favorites/<user_id>/add': 'Add song to favorites (GET: ?song_id=X)',
            'GET/POST /api/favorites/<user_id>/remove': 'Remove song from favorites (GET: ?song_id=X)',
            'GET /api/users/count': 'Get total user count'
        }
    })

@app.route('/api/songs', methods=['GET'])
def get_songs():
    """Return simplified list of all songs"""
    songs, error = get_songs_data()
    
    if error:
        return jsonify({'error': error}), 500
    
    simplified = [{
        'title': s.get('title'),
        'artist': s.get('artist', 'Unknown'),
        'url': s.get('url'),
        'difficulty': s.get('difficulty', 'Normal'),
        'thumbnail': s.get('thumbnail'),
        'id': s.get('url', '').split('/')[-1],
        'categories': s.get('categories', [])
    } for s in songs]
    
    return jsonify({
        'count': len(simplified),
        'songs': simplified
    })

@app.route('/api/songs/full', methods=['GET'])
def get_songs_full():
    """Return complete data for all songs including sheet music"""
    songs, error = get_songs_data()
    
    if error:
        return jsonify({'error': error}), 500
    
    return jsonify({
        'count': len(songs),
        'songs': songs
    })

@app.route('/api/song/<path:song_id>', methods=['GET'])
def get_song(song_id):
    """Get specific song by ID"""
    songs, error = get_songs_data()
    
    if error:
        return jsonify({'error': error}), 500
    
    for song in songs:
        url = song.get('url', '')
        if song_id in url or url.endswith(f'/{song_id}'):
            return jsonify(song)
    
    return jsonify({'error': 'Song not found'}), 404

@app.route('/api/search', methods=['GET'])
def search_songs():
    """Search songs by title or artist"""
    query = request.args.get('q', '').lower().strip()
    
    if not query:
        return jsonify({'error': 'Query parameter "q" is required'}), 400
    
    songs, error = get_songs_data()
    
    if error:
        return jsonify({'error': error}), 500
    
    results = []
    for song in songs:
        title = song.get('title', '').lower()
        artist = song.get('artist', '').lower()
        
        if query in title or query in artist:
            results.append(song)
    
    return jsonify({
        'query': query,
        'count': len(results),
        'results': results
    })

@app.route('/api/categories', methods=['GET'])
def get_categories():
    """Get all available categories"""
    songs, error = get_songs_data()
    
    if error:
        return jsonify({'error': error}), 500
    
    categories = set()
    for song in songs:
        for cat in song.get('categories', []):
            categories.add(cat)
    
    return jsonify({
        'count': len(categories),
        'categories': sorted(list(categories))
    })

@app.route('/api/category/<path:category_name>', methods=['GET'])
def get_songs_by_category(category_name):
    """Get songs filtered by category"""
    songs, error = get_songs_data()
    
    if error:
        return jsonify({'error': error}), 500
    
    filtered = []
    for song in songs:
        categories = [c.lower() for c in song.get('categories', [])]
        if category_name.lower() in categories:
            filtered.append(song)
    
    return jsonify({
        'category': category_name,
        'count': len(filtered),
        'songs': filtered
    })

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get database statistics"""
    songs, error = get_songs_data()
    
    if error:
        return jsonify({'error': error}), 500
    
    all_favs, _ = get_all_favorites()
    
    total_songs = len(songs)
    artists = set()
    difficulties = {}
    categories = set()
    total_sheets = 0
    
    for song in songs:
        artist = song.get('artist', 'Unknown')
        if artist and artist != 'Unknown Artist':
            artists.add(artist)
        
        difficulty = song.get('difficulty', 'Unknown')
        difficulties[difficulty] = difficulties.get(difficulty, 0) + 1
        
        for cat in song.get('categories', []):
            categories.add(cat)
        
        total_sheets += len(song.get('sheets', []))
    
    return jsonify({
        'total_songs': total_songs,
        'total_artists': len(artists),
        'total_categories': len(categories),
        'total_sheets': total_sheets,
        'total_users': len(all_favs),
        'total_favorites': sum(len(favs) for favs in all_favs.values()),
        'difficulties': difficulties,
        'database_file': SHEETS_FILE_PATH,
        'repository': GITHUB_REPO
    })

@app.route('/api/random', methods=['GET'])
def get_random_song():
    """Get a random song"""
    import random
    
    songs, error = get_songs_data()
    
    if error:
        return jsonify({'error': error}), 500
    
    if not songs:
        return jsonify({'error': 'No songs available'}), 404
    
    return jsonify(random.choice(songs))

@app.route('/api/favorites/<user_id>', methods=['GET'])
def get_favorites_route(user_id):
    """Get specific user's favorites"""
    favorites, error = get_user_favorites(user_id)
    
    if error and "not configured" not in error:
        favorites = []
    
    return jsonify({
        'user_id': user_id,
        'count': len(favorites),
        'favorites': favorites
    })

# ✅ YENİ: GET ve POST desteği
@app.route('/api/favorites/<user_id>/add', methods=['GET', 'POST'])
def add_favorite(user_id):
    """Add a song to user's favorites - Supports both GET and POST"""
    
    # Get song_id from query params (GET) or JSON body (POST)
    if request.method == 'GET':
        song_id = request.args.get('song_id')
    else:
        data = request.get_json()
        song_id = data.get('song_id') if data else None
    
    if not song_id:
        return jsonify({'error': 'song_id is required'}), 400
    
    favorites, error = get_user_favorites(user_id)
    if error:
        return jsonify({'error': error}), 500
    
    if song_id in favorites:
        return jsonify({
            'message': 'Already in favorites',
            'user_id': user_id,
            'favorites': favorites
        })
    
    favorites.append(song_id)
    
    success, error = update_user_favorites(user_id, favorites)
    if not success:
        return jsonify({'error': error}), 500
    
    return jsonify({
        'message': 'Added to favorites',
        'user_id': user_id,
        'count': len(favorites),
        'favorites': favorites
    })

# ✅ YENİ: GET ve POST desteği
@app.route('/api/favorites/<user_id>/remove', methods=['GET', 'POST'])
def remove_favorite(user_id):
    """Remove a song from user's favorites - Supports both GET and POST"""
    
    # Get song_id from query params (GET) or JSON body (POST)
    if request.method == 'GET':
        song_id = request.args.get('song_id')
    else:
        data = request.get_json()
        song_id = data.get('song_id') if data else None
    
    if not song_id:
        return jsonify({'error': 'song_id is required'}), 400
    
    favorites, error = get_user_favorites(user_id)
    if error:
        return jsonify({'error': error}), 500
    
    if song_id in favorites:
        favorites.remove(song_id)
        
        success, error = update_user_favorites(user_id, favorites)
        if not success:
            return jsonify({'error': error}), 500
        
        return jsonify({
            'message': 'Removed from favorites',
            'user_id': user_id,
            'count': len(favorites),
            'favorites': favorites
        })
    else:
        return jsonify({
            'message': 'Not in favorites',
            'user_id': user_id,
            'favorites': favorites
        })

@app.route('/api/users/count', methods=['GET'])
def get_user_count():
    """Get total number of users"""
    all_favs, error = get_all_favorites()
    
    if error:
        return jsonify({'error': error}), 500
    
    return jsonify({
        'total_users': len(all_favs),
        'users': list(all_favs.keys())
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    print(f"""
    ╔═══════════════════════════════════════╗
    ║   🎹 Matcha Piano Sheets API Server   ║
    ╠═══════════════════════════════════════╣
    ║   Port: {port}                        ║
    ║   Debug: {debug}                      ║
    ║   Multi-User: ✓                       ║
    ║   GET Support: ✓ (NEW)                ║
    ║   Repository: {GITHUB_REPO}           ║
    ╚═══════════════════════════════════════╝
    """)
    
    app.run(host='0.0.0.0', port=port, debug=debug)
