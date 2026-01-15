# 🔥 COOKIE & PROXY SYSTEM - USER GUIDE

## NEW FEATURES ADDED ✅

### 1. **Cookie Support for Protected Videos**
- **What it does**: Allows downloading age-restricted, private, or login-required videos
- **How to use**:
  1. Install browser extension: "Get cookies.txt" (Chrome/Firefox)
  2. Visit the platform (YouTube, Instagram, TikTok) and login
  3. Click the extension icon → Export cookies.txt
  4. In AG Studio: Click **Settings** button (top right)
  5. Under "🍪 Cookies" → Click **Upload**
  6. Select your cookies.txt file
  7. Now downloads will use your authentication!

### 2. **Proxy Support (Downloads & Browser)**
- **What it does**: Routes all traffic through a proxy server
- **Use cases**: 
  - Bypass geo-restrictions
  - Hide your IP
  - Access blocked content
  - Use residential/datacenter proxies

- **How to configure**:
  1. Click **Settings** button (top right)
  2. Under "🌐 Proxy":
     - Check **Enable**
     - Enter proxy in format: `186.96.50.113:999`
     - Click **Save**
  3. Proxy applies to:
     - ✅ All video downloads (yt-dlp)
     - ✅ Browser sessions (Playwright)
     - ✅ Direct file downloads

### 3. **Supported Proxy Formats**
```
# Simple IP:PORT
186.96.50.113:999

# With protocol
http://186.96.50.113:999
https://186.96.50.113:999
socks5://186.96.50.113:999

# With authentication
user:password@186.96.50.113:999
http://user:password@186.96.50.113:999
```

---

## HOW IT WORKS

### Cookie Flow:
1. Upload `cookies.txt` → Saved to project root
2. Download job starts → Checks if `cookies.txt` exists
3. If found → Passes to `yt-dlp` via `--cookies` flag
4. yt-dlp uses your session → Downloads authenticated content
5. Delete anytime via Settings panel

### Proxy Flow:
1. Configure proxy in Settings → Saved to `admin_config.json`
2. **For Downloads**:
   - Job reads proxy from `admin_config.json`
   - Passes to `yt-dlp` via `--proxy` flag
   - Also used for direct HTTP downloads via `requests`
3. **For Browser**:
   - Browser reads proxy from `admin_config.json`
   - Applies to Playwright context
   - All browser traffic routed through proxy

---

## TROUBLESHOOTING

### Cookies Not Working?
- ✅ Make sure you're logged in before exporting
- ✅ Use "Netscape" format cookies (standard from extension)
- ✅ Re-export cookies every few days (they expire)
- ✅ Check cookie status shows file size in Settings panel

### Proxy Not Working?
- ✅ Test proxy with curl: `curl --proxy http://IP:PORT https://google.com`
- ✅ Check proxy is alive and accepting connections
- ✅ For SOCKS5, make sure yt-dlp supports it
- ✅ Check logs for proxy errors

### Downloads Still Failing?
- ✅ Try different proxy
- ✅ Re-export fresh cookies
- ✅ Some platforms block all proxies (use residential)
- ✅ Check platform ToS (some prohibit automated access)

---

## TECHNICAL DETAILS

### Files Modified:
- `services/video_service.py` - Added cookie & proxy support
- `services/browser_service.py` - Added proxy to Playwright
- `task_queue/handlers.py` - Pass cookies/proxy to download_video()
- `routes/settings.py` - NEW: API endpoints for cookie/proxy management
- `templates/_settings_panel.html` - NEW: Settings UI panel
- `app.py` - Register settings blueprint

### API Endpoints:
```
GET  /api/settings/cookies     - Check cookie status
POST /api/settings/cookies     - Upload cookies.txt
DELETE /api/settings/cookies   - Delete cookies.txt

GET  /api/settings/proxy       - Get proxy config
POST /api/settings/proxy       - Save proxy config
```

### Storage:
- Cookies: `cookies.txt` (project root)
- Proxy config: `admin_config.json` (project root)

---

## BEST PRACTICES

### For Cookies:
1. **Security**: Never share your cookies.txt - it contains your session
2. **Rotation**: Re-export cookies weekly
3. **Platform-Specific**: Different cookies for YouTube, Instagram, TikTok
4. **Delete After Use**: Remove cookies.txt when done

### For Proxies:
1. **Residential > Datacenter**: Residential proxies less likely to be blocked
2. **Rotation**: Rotate proxies if one gets blocked
3. **Authentication**: Use proxies with auth for better security
4. **Testing**: Test proxy before bulk downloads

---

## EXAMPLE WORKFLOW

### Downloading Private YouTube Video:
1. Login to YouTube in Chrome
2. Install "Get cookies.txt" extension
3. Export cookies → Save as `cookies.txt`
4. Open AG Studio → Click **Settings**
5. Upload `cookies.txt`
6. Paste YouTube URL → Download
7. ✅ Video downloads using your authentication!

### Using Proxy for Geo-Blocked Content:
1. Get proxy from provider: `186.96.50.113:999`
2. Click **Settings** → Enable Proxy
3. Enter: `186.96.50.113:999`
4. Save
5. All downloads now route through proxy
6. ✅ Access geo-blocked content!

---

## STATUS: ✅ FULLY IMPLEMENTED & TESTED

Both cookie and proxy systems are now live and working!
