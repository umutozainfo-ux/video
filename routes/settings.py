"""
API endpoints for cookie and proxy management
"""
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
import os
import json

settings_bp = Blueprint('settings', __name__, url_prefix='/api/settings')

@settings_bp.route('/cookies', methods=['GET', 'POST', 'DELETE'])
def manage_cookies():
    """Manage cookies.txt file"""
    cookies_path = os.path.join(os.getcwd(), 'cookies.txt')
    
    if request.method == 'GET':
        # Check if cookies file exists
        exists = os.path.exists(cookies_path)
        size = os.path.getsize(cookies_path) if exists else 0
        return jsonify({
            'exists': exists,
            'size': size,
            'path': 'cookies.txt'
        })
    
    elif request.method == 'POST':
        # Upload new cookies file
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Save cookies file
        file.save(cookies_path)
        return jsonify({'message': 'Cookies uploaded successfully', 'path': 'cookies.txt'})
    
    elif request.method == 'DELETE':
        # Delete cookies file
        if os.path.exists(cookies_path):
            os.remove(cookies_path)
            return jsonify({'message': 'Cookies deleted'})
        return jsonify({'error': 'Cookies file not found'}), 404

@settings_bp.route('/proxy', methods=['GET', 'POST'])
def manage_proxy():
    """Manage proxy settings"""
    config_path = os.path.join(os.getcwd(), 'admin_config.json')
    
    if request.method == 'GET':
        # Load current proxy setting
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            return jsonify({
                'proxy': config.get('proxy', ''),
                'proxy_enabled': config.get('proxy_enabled', False)
            })
        except:
            return jsonify({'proxy': '', 'proxy_enabled': False})
    
    elif request.method == 'POST':
        # Save proxy setting
        data = request.get_json() or {}
        proxy = data.get('proxy', '').strip()
        proxy_enabled = data.get('proxy_enabled', False)
        
        try:
            # Load existing config
            with open(config_path, 'r') as f:
                config = json.load(f)
        except:
            config = {}
        
        config['proxy'] = proxy
        config['proxy_enabled'] = proxy_enabled
        
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        return jsonify({'message': 'Proxy settings saved', 'proxy': proxy, 'proxy_enabled': proxy_enabled})

@settings_bp.route('/proxy/test', methods=['POST'])
def test_proxy():
    """Test proxy speed and connectivity"""
    import time
    import requests
    
    config_path = os.path.join(os.getcwd(), 'admin_config.json')
    proxy = None
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
            if config.get('proxy_enabled') and config.get('proxy'):
                proxy = config['proxy'].strip()
                if proxy and not proxy.startswith('http'):
                    proxy = f'http://{proxy}'
    except:
        return jsonify({'error': 'Proxy not configured'}), 400
        
    if not proxy:
        return jsonify({'error': 'Proxy is disabled or empty'}), 400
        
    test_url = "https://www.google.com"
    proxies = {'http': proxy, 'https': proxy}
    
    stats = {}
    try:
        # Measure Latency (Ping)
        start_time = time.time()
        response = requests.get(test_url, proxies=proxies, timeout=10)
        latency = (time.time() - start_time) * 1000 # ms
        stats['latency_ms'] = round(latency, 2)
        stats['status_code'] = response.status_code
        
        # Measure Download Speed (Small 1MB file or similar if available, or just headers)
        # Using a reliable CDN file for speed test
        speed_test_url = "https://ajax.googleapis.com/ajax/libs/jquery/3.6.0/jquery.min.js"
        start_time = time.time()
        response = requests.get(speed_test_url, proxies=proxies, timeout=15)
        duration = time.time() - start_time
        size_kb = len(response.content) / 1024
        speed_kbps = size_kb / duration if duration > 0 else 0
        
        stats['download_speed_kbps'] = round(speed_kbps, 2)
        stats['file_size_kb'] = round(size_kb, 2)
        stats['success'] = True
        
        # Also get IP to verify proxy is working
        try:
            ip_res = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=5)
            stats['proxy_ip'] = ip_res.json().get('ip', 'Unknown')
        except:
            stats['proxy_ip'] = "Could not verify IP"
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 200 # Return 200 so UI can show the error gracefully
        
    return jsonify(stats)
