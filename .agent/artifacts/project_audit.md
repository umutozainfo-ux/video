# PROJECT AUDIT & IMPROVEMENTS PLAN

## Issues Found & Fixes Needed

### 🔴 CRITICAL ISSUES

1. **Cookie Support Missing**
   - **Problem**: yt-dlp downloads fail on age-restricted or login-required videos
   - **Solution**: Add cookies.txt support with UI to upload/update/delete
   - **Status**: TO IMPLEMENT

2. **Proxy Support Missing**
   - **Problem**: No proxy configuration for downloads or browser
   - **Solution**: Add proxy input field + browser proxy configuration
   - **Status**: TO IMPLEMENT

3. **PWA Update Not Working**
   - **Problem**: Update button doesn't trigger reload properly
   - **Solution**: Fix service worker activation logic
   - **Status**: FIXED (previous session)

4. **Job Queue Memory**
   - **Problem**: Doesn't reload pending jobs on restart
   - **Solution**: Already implemented in job_queue.py line 39-51
   - **Status**: ✅ WORKING

### 🟡 MEDIUM PRIORITY

5. **Browser State Not Persistent**
   - **Problem**: Browser cookies/session lost on disconnect
   - **Solution**: Save browser state to disk before closing
   - **Status**: TO IMPROVE

6. **No Video Preview Errors**
   - **Problem**: If video file is corrupted/missing, player shows nothing
   - **Solution**: Add file existence check + error placeholder
   - **Status**: TO IMPLEMENT

7. **Caption Upload Missing**
   - **Problem**: Can generate captions but can't upload existing SRT/ASS files
   - **Solution**: Add caption file upload button
   - **Status**: TO IMPLEMENT

8. **No Batch Operations**
   - **Problem**: Can only process one video at a time in UI
   - **Solution**: Multi-select with batch caption/convert buttons
   - **Status**: PARTIAL (delete exists)

### 🟢 MINOR ISSUES

9. **Font Files Not in Git**
   - **Problem**: fonts/ directory will be empty on fresh clone
   - **Solution**: Add fonts to .gitignore but keep build.py download
   - **Status**: ✅ WORKING (build.py downloads)

10. **No Download Progress in UI**
    - **Problem**: yt-dlp progress not shown until job completes
    - **Solution**: Already hooked in video_service.py line 48
    - **Status**: ✅ WORKING

11. **Browser Download Modal Not Auto-Opening**
    - **Problem**: User must manually click "Safe Import"
    - **Solution**: Auto-show modal when browser download completes
    - **Status**: TO ENHANCE

12. **No Error Recovery**
    - **Problem**: Failed jobs stay in "failed" state forever
    - **Solution**: Add "Retry" button (already exists in api.py line 354-362)
    - **Status**: ✅ IMPLEMENTED

---

## NEW FEATURES TO ADD

### 1. Cookie Management System
**Files to Create/Modify**:
- `cookies.txt` (user uploads to root directory)
- `templates/index.html` - Add cookie management panel
- `services/video_service.py` - Add cookies to yt-dlp options
- `routes/api.py` - Add cookie upload/delete endpoints

**Implementation**:
- Upload cookies.txt from browser extension (e.g., Get cookies.txt)
- Use in yt-dlp for authenticated downloads
- Delete/update via UI button

### 2. Proxy Configuration
**Files to Modify**:
- `admin_config.json` - Add proxy field
- `templates/index.html` - Add proxy input in download section
- `services/video_service.py` - Add proxy to yt-dlp
- `services/browser_service.py` - Add proxy to playwright

**Implementation**:
- Input field for proxy (IP:PORT or http://IP:PORT)
- Optional auth (username:password@IP:PORT)
- Toggle on/off per download

### 3. Caption File Import
**Implementation**:
- File upload for .srt/.ass/.vtt files
- Associate with existing video
- Show in caption links section

---

## IMPLEMENTATION PRIORITY

### Phase 1 (NOW):
1. ✅ Cookie support for yt-dlp
2. ✅ Proxy support for yt-dlp
3. ✅ Proxy support for browser
4. ✅ Cookie upload UI panel

### Phase 2 (Next):
5. Caption file upload
6. Browser state persistence
7. Video file validation
8. Batch caption generation

### Phase 3 (Enhancement):
9. Auto-open download modal
10. Download history
11. Preset management
12. Template system for caption styles
