// Global fetch interceptor
const originalFetch = window.fetch;
window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    if (response.status === 401) window.location.href = '/login';
    return response;
};

// State
let currentProjectId = null;
let currentView = 'dashboard';
let jobMonitorInterval = null;
let viewPollingInterval = null; // Interval for currently active view
let selectedVideoIds = new Set();
let previousJobStatuses = {}; // Track job status changes for notifications

// Init
document.addEventListener('DOMContentLoaded', () => {
    switchView('dashboard');
    startJobMonitor();
    loadProjects();
    requestNotificationPermission();
    loadSavedStyles();
    registerServiceWorker();
});

// --- PWA Service Worker ---
let newWorker;

function registerServiceWorker() {
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/sw.js').then(reg => {
                console.log('SW Registered:', reg);

                reg.addEventListener('updatefound', () => {
                    newWorker = reg.installing;
                    newWorker.addEventListener('statechange', () => {
                        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                            showUpdateNotification();
                        }
                    });
                });
            }).catch(err => console.log('SW Registration Failed:', err));
        });

        let refreshing;
        navigator.serviceWorker.addEventListener('controllerchange', () => {
            if (refreshing) return;
            window.location.reload();
            refreshing = true;
        });
    }
}

function showUpdateNotification() {
    const btn = document.getElementById('pwaUpdateBtn');
    const txt = document.getElementById('pwaBtnText');
    if (btn && txt) {
        btn.style.background = 'rgba(239, 68, 68, 0.1)';
        btn.style.color = 'var(--danger)';
        txt.innerHTML = `Update Available`;
        document.querySelector('#pwaUpdateBtn i').classList.add('fa-spin');
        showError('New update available! Click the red button in sidebar.', false);
    }
}

function updatePWA() {
    const btn = document.getElementById('pwaUpdateBtn');
    const txt = document.getElementById('pwaBtnText');

    if (newWorker) {
        if (txt) txt.textContent = "Updating...";
        newWorker.postMessage({ type: 'SKIP_WAITING' });
    } else {
        // Manual check / Refresh
        if (txt) txt.textContent = "Checking...";
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.getRegistration().then(reg => {
                if (reg) {
                    reg.update().then(() => {
                        if (!reg.installing && !reg.waiting) {
                            if (txt) txt.textContent = "Up to date!";
                            setTimeout(() => { if (txt) txt.textContent = "Check Updates"; }, 2000);
                        }
                    });
                } else {
                    window.location.reload();
                }
            });
        } else {
            window.location.reload();
        }
    }
}

function loadSavedStyles() {
    const saved = localStorage.getItem('ag_caption_style');
    if (saved) {
        const s = JSON.parse(saved);
        if (document.getElementById('capFontSize')) document.getElementById('capFontSize').value = s.fontSize || 24;
        if (document.getElementById('capFontName')) document.getElementById('capFontName').value = s.fontName || 'Arial Black';
        if (document.getElementById('capPrimaryColor')) document.getElementById('capPrimaryColor').value = s.primaryColor || '#ffffff';
        if (document.getElementById('capOutlineColor')) document.getElementById('capOutlineColor').value = s.outlineColor || '#000000';
        if (document.getElementById('capAlignment')) document.getElementById('capAlignment').value = s.alignment || '2';
        if (document.getElementById('capBackgroundColor')) document.getElementById('capBackgroundColor').value = s.backgroundColor || '#000000';
        if (document.getElementById('capLetterSpacing')) document.getElementById('capLetterSpacing').value = s.letterSpacing || '0';
        if (document.getElementById('capShadowBlur')) document.getElementById('capShadowBlur').value = s.shadowBlur || '4';

        if (s.borderStyle === '3') {
            document.getElementById('styleBox').checked = true;
            document.getElementById('boxOptions').style.display = 'block';
        } else {
            document.getElementById('styleOutline').checked = true;
        }
    }
}

function saveCurrentStyles() {
    const style = {
        fontSize: document.getElementById('capFontSize').value,
        fontName: document.getElementById('capFontName').value,
        primaryColor: document.getElementById('capPrimaryColor').value,
        outlineColor: document.getElementById('capOutlineColor').value,
        alignment: document.getElementById('capAlignment').value,
        backgroundColor: document.getElementById('capBackgroundColor').value,
        borderStyle: document.querySelector('input[name="borderStyle"]:checked').value,
        letterSpacing: document.getElementById('capLetterSpacing') ? document.getElementById('capLetterSpacing').value : '0',
        shadowBlur: document.getElementById('capShadowBlur') ? document.getElementById('capShadowBlur').value : '4'
    };
    localStorage.setItem('ag_caption_style', JSON.stringify(style));
}

function requestNotificationPermission() {
    if ('Notification' in window) {
        Notification.requestPermission();
    }
}

// Navigation
function switchView(viewName) {
    document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));

    const viewEl = document.getElementById(`view-${viewName}`);
    if (viewEl) viewEl.classList.add('active');

    const navLink = document.querySelector(`.nav-item[onclick="switchView('${viewName}')"]`);
    if (navLink) navLink.classList.add('active');

    // Clear existing view polling
    if (viewPollingInterval) {
        clearInterval(viewPollingInterval);
        viewPollingInterval = null;
    }

    if (viewName === 'dashboard') {
        loadDashboard();
        viewPollingInterval = setInterval(loadDashboard, 5000);
    }
    if (viewName === 'projects') {
        loadProjects();
        viewPollingInterval = setInterval(loadProjects, 10000);
    }
    if (viewName === 'jobs') {
        loadFullJobHistory();
        viewPollingInterval = setInterval(loadFullJobHistory, 6000);
    }
    if (viewName === 'storage') {
        loadStorageData();
        viewPollingInterval = setInterval(loadStorageData, 10000);
    }
    if (viewName === 'users') {
        loadUsers();
        viewPollingInterval = setInterval(loadUsers, 10000);
    }
    if (viewName === 'editor') {
        // Editor doesn't use standard switchView often, usually openProject.
        // But if we toggle views, we should start polling for current project.
        if (currentProjectId) {
            viewPollingInterval = setInterval(() => loadProjectVideos(currentProjectId), 3000);
        }
    }

    currentView = viewName;
    toggleSidebar(false);
}

function toggleSidebar(force) {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('mobileOverlay');
    if (!sidebar) return;
    if (force === false) {
        sidebar.classList.remove('open');
        overlay.classList.remove('open');
    } else {
        sidebar.classList.toggle('open');
        overlay.classList.toggle('open');
    }
}

// --- Dashboard ---
async function loadDashboard() {
    try {
        const res = await fetch('/api/queue/stats');
        const stats = await res.json();

        document.getElementById('stat-active-jobs').textContent = stats.active_jobs || 0;
        document.getElementById('stat-queue-size').textContent = stats.queue_size || 0;
        document.getElementById('stat-completed-today').textContent = stats.completed_today || 0;

        const jobsRes = await fetch('/api/jobs');
        const jobs = await jobsRes.json();
        const list = document.getElementById('dashboard-activity-list');
        list.innerHTML = '';

        jobs.slice(0, 5).forEach(job => {
            const div = document.createElement('div');
            div.className = 'list-item';
            div.innerHTML = `
                <div>
                    <div style="font-weight:600;">${job.type}</div>
                    <div style="font-size:0.8rem; color:var(--text-muted);">${new Date(job.created_at).toLocaleTimeString()}</div>
                </div>
                <span class="job-status status-${job.status}">${job.status}</span>
            `;
            list.appendChild(div);
        });
    } catch (e) { console.error(e); }
}

// --- Projects ---
async function loadProjects() {
    try {
        const res = await fetch('/api/projects');
        const projects = await res.json();
        const grid = document.getElementById('projects-grid');
        grid.innerHTML = '';

        if (projects.length === 0) {
            grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:40px; color:var(--text-muted);">No projects yet. Create one above.</div>';
            return;
        }

        projects.forEach(p => {
            const card = document.createElement('div');
            card.className = 'card project-card';
            card.style.position = 'relative';
            card.innerHTML = `
                <div onclick="selectProjectById('${p.id}', '${p.name.replace(/'/g, "\\'")}')" style="cursor:pointer; flex:1;">
                    <i class="fas fa-folder folder-icon"></i>
                    <div style="font-weight:600; font-size:1.1rem; margin-bottom:4px;">${p.name}</div>
                    <div style="color:var(--text-muted); font-size:0.8rem;">ID: ${p.id.substr(0, 8)}</div>
                </div>
                <button onclick="deleteProject('${p.id}')" class="btn-icon-delete" style="position:absolute; top:12px; right:12px; background:none; border:none; color:#ef4444; opacity:0.6; cursor:pointer;" title="Delete Project">
                    <i class="fas fa-trash"></i>
                </button>
            `;
            grid.appendChild(card);
        });
    } catch (e) { console.error(e); }
}

function selectProjectById(id, name) {
    currentProjectId = id;
    document.getElementById('current-project-title').textContent = name;
    document.getElementById('current-project-id').textContent = `ID: ${id}`;

    // Clear existing view polling
    if (viewPollingInterval) {
        clearInterval(viewPollingInterval);
    }

    switchView('project-detail');
    loadVideos(id);

    // Start polling for this project's videos (Reduced rate)
    viewPollingInterval = setInterval(() => loadVideos(id), 5000);
}

async function createProject() {
    const name = document.getElementById('newProjectName').value.trim();
    if (!name) return showError('Project name required');
    try {
        const res = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        if (res.ok) {
            document.getElementById('newProjectName').value = '';
            loadProjects();
            showError('Project created!', false);
        }
    } catch (e) { showError(e.message); }
}

async function deleteProject(id) {
    if (!confirm('Permanently delete this project and all its videos?')) return;
    try {
        const res = await fetch(`/api/projects/${id}`, { method: 'DELETE' });
        if (res.ok) {
            showError('Project deleted', false);
            loadProjects();
        }
    } catch (e) { showError('Failed to delete project'); }
}

function refreshProjects() { loadProjects(); }

// --- Video Manager ---
async function loadVideos(projectId) {
    if (!projectId) return;
    selectedVideoIds.clear();
    updateBulkDeleteButton();
    const list = document.getElementById('videoList');
    list.innerHTML = '<li style="padding:10px;">Loading...</li>';
    try {
        const res = await fetch(`/api/projects/${projectId}/videos`);
        const videos = await res.json();
        list.innerHTML = '';
        if (!videos.length) {
            list.innerHTML = '<li style="padding:10px; color:var(--text-muted);">No videos found.</li>';
            return;
        }
        const originals = videos.filter(v => !v.is_clip);
        const clips = videos.filter(v => v.is_clip);

        const render = (v) => {
            const li = document.createElement('li');
            li.style.padding = '8px 12px';
            li.style.borderBottom = '1px solid #f0f0f0';
            li.style.display = 'flex';
            li.style.alignItems = 'center';
            li.style.gap = '10px';
            li.style.cursor = 'pointer';

            li.innerHTML = `
                <input type="checkbox" onclick="event.stopPropagation(); toggleVideoSelection('${v.id}')" style="cursor:pointer; width:16px; height:16px;">
                <div onclick="openVideoById('${v.id}', '${v.filename}', '${v.project_id}', '${(v.title || v.filename).replace(/'/g, "\\'")}')" style="display:flex; align-items:center; gap:10px; flex:1; overflow:hidden;">
                    <i class="fas fa-play-circle" style="color:var(--primary); font-size:1.2rem;"></i>
                    <div style="overflow:hidden;">
                        <div style="font-weight:600; white-space:nowrap; text-overflow:ellipsis;">${v.title || v.filename}</div>
                        <div style="font-size:0.75rem; color:var(--text-muted);">${v.filename}</div>
                    </div>
                </div>
            `;
            return li;
        };

        if (originals.length) {
            const h = document.createElement('li'); h.innerHTML = '<b>Originals</b>'; h.style.padding = '8px 12px'; h.style.background = '#f8fafc'; h.style.fontSize = '0.8rem';
            list.appendChild(h);
            originals.forEach(v => list.appendChild(render(v)));
        }
        if (clips.length) {
            const h = document.createElement('li'); h.innerHTML = '<b>Clips</b>'; h.style.padding = '8px 12px'; h.style.background = '#f8fafc'; h.style.fontSize = '0.8rem';
            list.appendChild(h);
            clips.forEach(v => list.appendChild(render(v)));
        }
    } catch (e) { console.error(e); }
}

function toggleVideoSelection(id) {
    if (selectedVideoIds.has(id)) selectedVideoIds.delete(id);
    else selectedVideoIds.add(id);
    updateBulkDeleteButton();
}

function updateBulkDeleteButton() {
    const btn = document.getElementById('bulkDeleteBtn');
    if (selectedVideoIds.size > 0) {
        btn.style.display = 'inline-flex';
        btn.innerHTML = `<i class="fas fa-trash"></i> Delete (${selectedVideoIds.size})`;
    } else {
        btn.style.display = 'none';
    }
}

async function confirmBulkDelete() {
    if (!selectedVideoIds.size || !confirm(`Delete all ${selectedVideoIds.size} selected videos?`)) return;
    try {
        const res = await fetch(`/api/projects/${currentProjectId}/videos/bulk-delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ video_ids: Array.from(selectedVideoIds) })
        });
        if (res.ok) {
            showError(`${selectedVideoIds.size} videos deleted`, false);
            loadVideos(currentProjectId);
        }
    } catch (e) { showError('Bulk delete failed'); }
}

async function startDownload() {
    const url = document.getElementById('urlInput').value.trim();
    if (!url || !currentProjectId) return showError('URL and Project required');
    const resSelector = document.getElementById('downloadRes');
    const resolution = resSelector ? resSelector.value : '720';

    try {
        await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, project_id: currentProjectId, resolution })
        });
        showError('Processing started!', false);
        document.getElementById('urlInput').value = '';
    } catch (e) { showError(e.message); }
}

async function handleFileUpload(input) {
    if (!input.files[0] || !currentProjectId) return;
    const formData = new FormData();
    formData.append('file', input.files[0]);
    formData.append('project_id', currentProjectId);
    try {
        await fetch('/api/upload', { method: 'POST', body: formData });
        showError('Upload started!', false);
    } catch (e) { showError(e.message); }
}

// --- Player & Editor ---
function openVideoById(id, filename, projectId, title) {
    openVideo({ id, filename, project_id: projectId, title });
}

async function openVideo(video) {
    window.__currentVideo = { id: video.id, filename: video.filename, projectId: video.project_id, title: video.title };
    document.getElementById('videoContainer').style.display = 'block';
    document.getElementById('videoTitle').textContent = video.title || video.filename;

    const player = document.getElementById('videoPlayer');
    player.src = `/api/stream/${video.project_id}/${video.filename}`;
    player.load();

    const dlLink = document.getElementById('downloadLink');
    if (dlLink) {
        dlLink.href = `/api/video/${video.project_id}/${video.filename}`;
        dlLink.style.display = 'inline-flex';
    }

    initTimeline();
    loadCaptions(video.project_id, video.id);

    if (window.innerWidth < 768) document.getElementById('videoContainer').scrollIntoView({ behavior: 'smooth' });
}

async function loadCaptions(projectId, videoId) {
    try {
        const res = await fetch(`/api/projects/${projectId}/videos/${videoId}`);
        const data = await res.json();
        const div = document.getElementById('captionLinks');
        div.innerHTML = '';
        if (data.captions && data.captions.length) {
            data.captions.forEach(c => {
                const el = document.createElement('div');
                el.style.display = 'flex'; el.style.gap = '10px'; el.style.alignItems = 'center'; el.style.marginBottom = '8px';
                el.innerHTML = `
                    <i class="fas fa-file-alt" style="color:#6366f1;"></i>
                    <a href="/api/caption/${projectId}/${c.filename}" download style="color:var(--primary); text-decoration:none; font-size:0.9rem;">${c.filename}</a>
                    <button class="btn btn-secondary" style="padding:4px 8px; font-size:0.75rem;" onclick="burnCaptions('${c.id}', '${c.filename}')">🔥 Burn</button>
                `;
                div.appendChild(el);
            });
        } else {
            div.innerHTML = '<div style="color:var(--text-muted); font-size:0.9rem;">No captions generated yet.</div>';
        }
    } catch (e) { }
}

async function runCaptioning() {
    if (!window.__currentVideo) return;
    const level = document.getElementById('captionLevel').value;
    const model = prompt('Models: tiny, base, small. (Default: tiny)', 'tiny') || 'tiny';
    try {
        await fetch(`/api/projects/${window.__currentVideo.projectId}/videos/${window.__currentVideo.id}/caption`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ level, model })
        });
        showError('Captioning task submitted!', false);
    } catch (e) { showError(e.message); }
}

async function deleteCurrentVideo() {
    if (!window.__currentVideo || !confirm('Permanently delete this video?')) return;
    try {
        await fetch(`/api/projects/${window.__currentVideo.projectId}/videos/${window.__currentVideo.id}`, { method: 'DELETE' });
        document.getElementById('videoContainer').style.display = 'none';
        loadVideos(window.__currentVideo.projectId);
        showError('Video deleted', false);
    } catch (e) { showError(e.message); }
}

// --- Timeline Logic ---
let timelineMarkers = { in: 0, out: 0 };

function initTimeline() {
    const player = document.getElementById('videoPlayer');
    const track = document.getElementById('timelineTrack');
    const container = document.getElementById('timelineContainer');
    if (!container) return;

    container.style.display = 'block';

    player.onloadedmetadata = () => {
        timelineMarkers = { in: 0, out: player.duration || 0 };
        updateTimelineDisplay();
    };

    player.ontimeupdate = () => {
        const percent = (player.currentTime / player.duration) * 100;
        document.getElementById('playhead').style.left = percent + '%';
        updateTimelineDisplay();
    };

    track.onclick = (e) => {
        const rect = track.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const percent = x / rect.width;
        player.currentTime = percent * player.duration;
    };

    // Hotkeys
    const handleKeys = (e) => {
        if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
        const key = e.key.toLowerCase();
        if (key === 'i') setTimelineMarker('in');
        if (key === 'o') setTimelineMarker('out');
        if (key === ' ') { e.preventDefault(); player.paused ? player.play() : player.pause(); }
    };
    document.removeEventListener('keydown', window._timelineKeys);
    window._timelineKeys = handleKeys;
    document.addEventListener('keydown', handleKeys);
}

function setTimelineMarker(type) {
    const player = document.getElementById('videoPlayer');
    timelineMarkers[type] = player.currentTime;
    updateTimelineDisplay();
}

function updateTimelineDisplay() {
    const player = document.getElementById('videoPlayer');
    const overlay = document.getElementById('selectionOverlay');
    const text = document.getElementById('timelineTime');
    if (!player || !player.duration || !overlay || !text) return;

    const inP = (timelineMarkers.in / player.duration) * 100;
    const outP = (timelineMarkers.out / player.duration) * 100;
    overlay.style.left = inP + '%';
    overlay.style.width = Math.max(0, outP - inP) + '%';

    const fmt = (s) => isNaN(s) ? "00:00" : new Date(s * 1000).toISOString().substr(14, 5);
    text.textContent = `${fmt(player.currentTime)} / ${fmt(player.duration)} [Clip: ${fmt(timelineMarkers.in)} - ${fmt(timelineMarkers.out)}]`;
}

async function confirmTrimFromTimeline() {
    if (!window.__currentVideo) return;
    const start = timelineMarkers.in;
    const end = timelineMarkers.out;
    if (end <= start) return showError('Invalid range');
    const title = prompt('Name your clip:', 'New Clip') || 'Trimmed Clip';
    try {
        await fetch(`/api/projects/${window.__currentVideo.projectId}/videos/${window.__currentVideo.id}/trim`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ start_time: start, end_time: end, title })
        });
        showError('Trimming started!', false);
    } catch (e) { showError(e.message); }
}

// --- Splitting ---
function toggleSplitMenu() {
    const m = document.getElementById('splitMenu');
    m.style.display = m.style.display === 'block' ? 'none' : 'block';
}

function showSplitSettings(type) {
    document.getElementById('splitMenu').style.display = 'none';
    document.getElementById('splitSettings').style.display = 'block';
    ['sceneDetectOptions', 'fixedSplitOptions', 'trimOptions'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        if (id.startsWith(type) || (type === 'ai' && id === 'sceneDetectOptions') || (type === 'fixed' && id === 'fixedSplitOptions') || (type === 'trim' && id === 'trimOptions')) {
            el.style.display = 'block';
        } else {
            el.style.display = 'none';
        }
    });
}

function setTrimTime(target) {
    const player = document.getElementById('videoPlayer');
    document.getElementById(target === 'start' ? 'trimStart' : 'trimEnd').value = player.currentTime.toFixed(1);
}

async function confirmSplit() {
    if (!window.__currentVideo) return;
    const minLen = document.getElementById('minSceneLen').value;
    const threshold = document.getElementById('splitThreshold').value;
    try {
        await fetch(`/api/projects/${window.__currentVideo.projectId}/videos/${window.__currentVideo.id}/split-scenes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ min_scene_len: parseFloat(minLen), threshold: parseFloat(threshold) })
        });
        showError('Split task submitted', false);
        document.getElementById('splitSettings').style.display = 'none';
    } catch (e) { showError(e.message); }
}

async function confirmFixedSplit() {
    if (!window.__currentVideo) return;
    const interval = document.getElementById('splitInterval').value;
    try {
        await fetch(`/api/projects/${window.__currentVideo.projectId}/videos/${window.__currentVideo.id}/split-fixed`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ interval: parseFloat(interval) })
        });
        showError('Split task submitted', false);
        document.getElementById('splitSettings').style.display = 'none';
    } catch (e) { showError(e.message); }
}

async function confirmTrim() {
    if (!window.__currentVideo) return;
    const start = document.getElementById('trimStart').value;
    const end = document.getElementById('trimEnd').value;
    try {
        await fetch(`/api/projects/${window.__currentVideo.projectId}/videos/${window.__currentVideo.id}/trim`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ start_time: parseFloat(start), end_time: parseFloat(end), title: 'Manual Trim' })
        });
        showError('Trim task submitted', false);
        document.getElementById('splitSettings').style.display = 'none';
    } catch (e) { showError(e.message); }
}

// --- Captions & Burning ---
let pendingCaptionId = null;
function closeCaptionDesigner() { document.getElementById('captionDesignerModal').style.display = 'none'; }
function burnCaptions(id, filename) {
    pendingCaptionId = id;
    document.getElementById('captionDesignerModal').style.display = 'flex';
    applyPreset('hormozi');
}

function applyPreset(name) {
    const s = {
        hormozi: { f: 'Arial Black', sz: 32, c: '#ffff00', o: '#000000', a: '2', bs: '1', bg: '#000000', ls: '1', sb: '10' },
        beast: { f: 'Luckiest Guy', sz: 36, c: '#ffffff', o: '#000000', a: '2', bs: '1', bg: '#000000', ls: '2', sb: '6' },
        tiktok: { f: 'Bebas Neue', sz: 40, c: '#ffffff', o: '#000000', a: '10', bs: '3', bg: '#000000', ls: '1', sb: '0' },
        modern: { f: 'Oswald', sz: 28, c: '#ffffff', o: '#3b82f6', a: '2', bs: '1', bg: '#000000', ls: '0', sb: '4' }
    }[name];
    if (s) {
        document.getElementById('capFontSize').value = s.sz;
        document.getElementById('capFontName').value = s.f;
        document.getElementById('capPrimaryColor').value = s.c;
        document.getElementById('capOutlineColor').value = s.o;
        document.getElementById('capAlignment').value = s.a;
        document.getElementById('capBackgroundColor').value = s.bg;
        if (document.getElementById('capLetterSpacing')) document.getElementById('capLetterSpacing').value = s.ls;
        if (document.getElementById('capShadowBlur')) document.getElementById('capShadowBlur').value = s.sb;

        if (s.bs === '3') {
            document.getElementById('styleBox').checked = true;
            document.getElementById('boxOptions').style.display = 'block';
        } else {
            document.getElementById('styleOutline').checked = true;
            document.getElementById('boxOptions').style.display = 'none';
        }

        updateDesignerPreview();
        saveCurrentStyles();
    }
}

function updateDesignerPreview() {
    const p = document.getElementById('previewText');
    const borderStyle = document.querySelector('input[name="borderStyle"]:checked').value;

    p.style.fontSize = document.getElementById('capFontSize').value + 'px';
    p.style.fontFamily = document.getElementById('capFontName').value;
    p.style.color = document.getElementById('capPrimaryColor').value;
    p.style.letterSpacing = (document.getElementById('capLetterSpacing') ? document.getElementById('capLetterSpacing').value : '0') + 'px';
    p.textContent = p.textContent.toUpperCase(); // Force All-Caps in preview

    const oc = document.getElementById('capOutlineColor').value;
    const bg = document.getElementById('capBackgroundColor').value;
    const sb = document.getElementById('capShadowBlur') ? document.getElementById('capShadowBlur').value : '4';

    if (borderStyle === '3') {
        p.style.textShadow = 'none';
        p.style.backgroundColor = bg;
        p.style.padding = '10px 20px';
        p.style.borderRadius = '8px';
    } else {
        p.style.backgroundColor = 'transparent';
        p.style.padding = '0';
        p.style.textShadow = `0 0 ${sb}px ${oc}, 0 0 ${sb}px ${oc}`;
    }
}

// Attach preview update to inputs
['capFontSize', 'capFontName', 'capPrimaryColor', 'capOutlineColor', 'capAlignment', 'capBackgroundColor', 'capLetterSpacing', 'capShadowBlur'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.oninput = () => {
        updateDesignerPreview();
        saveCurrentStyles();
    };
});

document.querySelectorAll('input[name="borderStyle"]').forEach(radio => {
    radio.onchange = (e) => {
        document.getElementById('boxOptions').style.display = e.target.value === '3' ? 'block' : 'none';
        updateDesignerPreview();
        saveCurrentStyles();
    };
});

async function confirmStyledBurn() {
    if (!window.__currentVideo || !pendingCaptionId) return;
    const style = {
        fontSize: document.getElementById('capFontSize').value,
        fontName: document.getElementById('capFontName').value,
        primaryColor: document.getElementById('capPrimaryColor').value,
        outlineColor: document.getElementById('capOutlineColor').value,
        alignment: document.getElementById('capAlignment').value,
        backgroundColor: document.getElementById('capBackgroundColor').value,
        borderStyle: document.querySelector('input[name="borderStyle"]:checked').value,
        letterSpacing: document.getElementById('capLetterSpacing') ? document.getElementById('capLetterSpacing').value : 0,
        shadowBlur: document.getElementById('capShadowBlur') ? document.getElementById('capShadowBlur').value : 0
    };
    closeCaptionDesigner();
    try {
        await fetch(`/api/projects/${window.__currentVideo.projectId}/videos/${window.__currentVideo.id}/burn`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ caption_id: pendingCaptionId, style })
        });
        showError('Burning task submitted!', false);
    } catch (e) { showError('Burn failed'); }
}

// --- Job Monitoring ---
function startJobMonitor() {
    if (jobMonitorInterval) clearInterval(jobMonitorInterval);
    jobMonitorInterval = setInterval(updateJobs, 5000);
}

async function updateJobs() {
    try {
        const res = await fetch('/api/jobs');
        const jobs = await res.json();

        // Notification Check
        jobs.forEach(j => {
            const prevStatus = previousJobStatuses[j.id];
            if (prevStatus && prevStatus !== j.status) {
                if (j.status === 'completed') {
                    sendNotification(`Job Finished!`, `${j.type} task is complete.`);
                } else if (j.status === 'failed') {
                    sendNotification(`Job Failed`, `${j.type} task encountered an error.`);
                }
            }
            previousJobStatuses[j.id] = j.status;
        });

        const active = jobs.filter(j => ['pending', 'running', 'downloading', 'processing'].includes(j.status));
        const widget = document.getElementById('job-monitor-widget');
        const list = document.getElementById('active-jobs-list');

        if (active.length > 0) {
            widget.style.display = 'flex';
            list.innerHTML = '';
            active.forEach(j => {
                const msg = (j.output_data && j.output_data.progress_message) ? j.output_data.progress_message : j.status;
                const div = document.createElement('div');
                div.className = 'job-item';
                div.innerHTML = `
                    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                        <span style="font-weight:700; font-size:0.8rem; text-transform:uppercase;">${j.type}</span>
                        <span style="font-size:0.75rem; color:var(--text-muted);">${msg}</span>
                    </div>
                    <div class="progress-track"><div class="progress-fill" style="width:${j.progress || 0}%;"></div></div>
                `;
                list.appendChild(div);
            });
        } else {
            widget.style.display = 'none';
        }

        if (currentView === 'jobs') renderJobsTable(jobs);
        if (currentView === 'dashboard') loadDashboard();
    } catch (e) { }
}

function renderJobsTable(jobs) {
    const tbody = document.getElementById('full-jobs-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';
    jobs.forEach(j => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #f0f0f0';
        tr.innerHTML = `
            <td style="padding:12px; font-size:0.8rem;">${j.id.substr(0, 8)}</td>
            <td style="padding:12px;">${j.type}</td>
            <td style="padding:12px;"><span class="job-status status-${j.status}">${j.status}</span></td>
            <td style="padding:12px; font-size:0.8rem;">${new Date(j.created_at).toLocaleString()}</td>
            <td style="padding:12px;">
                <div style="display:flex; gap:8px;">
                    ${['running', 'pending'].includes(j.status) ? `<button class="btn btn-secondary" style="padding:4px 8px; font-size:0.7rem; color:var(--danger);" onclick="cancelJob('${j.id}')">Stop</button>` : ''}
                    <button class="btn-icon-delete" onclick="deleteJobHistory('${j.id}')" style="background:none; border:none; color:#ef4444; opacity:0.6; cursor:pointer;" title="Delete History">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function cancelJob(id) {
    if (!confirm('Stop this task?')) return;
    try { await fetch(`/api/jobs/${id}/cancel`, { method: 'POST' }); updateJobs(); } catch (e) { }
}

async function deleteJobHistory(id) {
    if (!confirm('Remove this job from history?')) return;
    try {
        const res = await fetch(`/api/jobs/${id}`, { method: 'DELETE' });
        if (res.ok) updateJobs();
    } catch (e) { }
}

function loadFullJobHistory() { updateJobs(); }

function showError(msg, isError = true) {
    const el = document.getElementById('errorMessage');
    el.textContent = msg;
    el.style.display = 'block';
    el.style.backgroundColor = isError ? '#fee2e2' : '#dcfce7';
    el.style.color = isError ? '#991b1b' : '#166534';
    el.style.borderLeft = `4px solid ${isError ? '#ef4444' : '#10b981'}`;
    setTimeout(() => el.style.display = 'none', 4000);
}

function sendNotification(title, body) {
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, {
            body: body,
            icon: 'https://cdn-icons-png.flaticon.com/512/711/711245.png'
        });
    }
}

function testNotification() {
    if (!('Notification' in window)) {
        showError('Notifications not supported by this browser');
        return;
    }
    if (Notification.permission === 'granted') {
        sendNotification('Test Active!', 'If you see this, your alerts are working.');
    } else {
        Notification.requestPermission().then(p => {
            if (p === 'granted') sendNotification('Success!', 'Alerts enabled.');
            else showError('Permission denied');
        });
    }
}

// --- Storage Logic ---
async function loadStorageData() {
    loadStorageStats();
    loadStorageFiles();
}

async function loadStorageStats() {
    try {
        const res = await fetch('/api/storage/stats');
        const stats = await res.json();

        document.getElementById('storage-disk-percent').textContent = Math.round(stats.disk.percent) + '%';
        const totalMB = Math.round((stats.app.uploads + stats.app.processed + stats.app.captions) / (1024 * 1024));
        document.getElementById('storage-app-total').textContent = totalMB + ' MB';
    } catch (e) { }
}

async function loadStorageFiles() {
    try {
        const res = await fetch('/api/storage/files');
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        const files = await res.json();
        const tbody = document.getElementById('storage-files-table');
        if (!tbody) return;
        tbody.innerHTML = '';

        if (files.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--text-muted);">No files found in app directories.</td></tr>';
            return;
        }

        files.forEach(f => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid #f0f0f0';
            const sizeMB = (f.size / (1024 * 1024)).toFixed(1);
            const safePath = f.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
            tr.innerHTML = `
                <td style="padding:12px;"><input type="checkbox" class="storage-checkbox" data-path="${safePath}"></td>
                <td style="padding:12px; font-size:12px; max-width:200px; overflow:hidden; text-overflow:ellipsis;" title="${f.name}">${f.name}</td>
                <td style="padding:12px;"><span class="job-status" style="background:#e2e8f0; color:#475569;">${f.type}</span></td>
                <td style="padding:12px;">${sizeMB} MB</td>
                <td style="padding:12px; font-size:11px;">${new Date(f.created_at).toLocaleDateString()}</td>
                <td style="padding:12px;">
                    <button class="btn btn-secondary" style="color:var(--danger); padding:4px 8px; font-size:10px;" onclick="deleteServerFile('${safePath}')">Delete</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Storage Error:", e);
        showError("Could not load storage files");
    }
}

async function deleteServerFile(path) {
    if (!confirm('Permanently delete this file from server?')) return;
    try {
        const res = await fetch('/api/storage/files/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });
        if (res.ok) {
            loadStorageData();
            showError('File deleted from server', false);
        }
    } catch (e) { showError('Delete failed'); }
}

// --- Admin / User Management ---
async function loadUsers() {
    try {
        const res = await fetch('/api/users');
        const users = await res.json();
        const tbody = document.getElementById('users-table-body');
        if (!tbody) return;
        tbody.innerHTML = '';
        users.forEach(u => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid #f1f5f9';
            tr.innerHTML = `
                <td style="padding:12px;">${u.username}</td>
                <td style="padding:12px;"><code style="background:#f1f5f9; padding:2px 6px; border-radius:4px;">${u.passcode}</code></td>
                <td style="padding:12px;"><span class="job-status" style="background:#e0f2fe; color:#0369a1;">${u.role}</span></td>
                <td style="padding:12px;">
                    ${u.role !== 'admin' ? `<button class="btn btn-secondary" style="color:var(--danger); padding:4px 8px; font-size:12px;" onclick="deleteUserAccount('${u.id}')">Remove</button>` : ''}
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) { console.error(e); }
}

async function adminCreateUser() {
    const username = document.getElementById('newUserUsername').value;
    const passcode = document.getElementById('newUserPasscode').value;
    if (!username || !passcode) return showError('Please fill all fields');

    try {
        const res = await fetch('/api/users', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, passcode })
        });
        if (res.ok) {
            document.getElementById('newUserUsername').value = '';
            document.getElementById('newUserPasscode').value = '';
            loadUsers();
        } else {
            const err = await res.json();
            showError(err.error || 'Failed to create user');
        }
    } catch (e) { showError('Network error'); }
}

async function deleteUserAccount(id) {
    if (!confirm('Are you sure you want to remove this passcode?')) return;
    try {
        const res = await fetch(`/api/users/${id}`, { method: 'DELETE' });
        if (res.ok) loadUsers();
    } catch (e) { showError('Delete failed'); }
}

// --- Storage Tools ---
function toggleAllStorage(master) {
    document.querySelectorAll('.storage-checkbox').forEach(cb => cb.checked = master.checked);
}

async function bulkDeleteFiles() {
    const selected = Array.from(document.querySelectorAll('.storage-checkbox:checked')).map(cb => cb.dataset.path);
    if (selected.length === 0) return showError('No files selected');
    if (!confirm(`Delete ${selected.length} files permanently?`)) return;

    try {
        const res = await fetch('/api/storage/bulk-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paths: selected })
        });
        if (res.ok) {
            showError(`Deleted ${selected.length} files`, false);
            loadStorageData();
        }
    } catch (e) { showError('Bulk delete failed'); }
}

async function cleanAllServer() {
    if (!confirm('WIPE ALL DOWNLOADS AND PROCESSED VIDEOS? This cannot be undone.')) return;
    try {
        const res = await fetch('/api/storage/cleanup', { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            showError(`Wiped ${data.count} files`, false);
            loadStorageData();
        }
    } catch (e) { showError('Cleanup failed'); }
}

async function makeVertical() {
    if (!currentVideoId) return showError('No video selected');
    try {
        const res = await fetch(`/api/projects/${currentProjectId}/videos/${currentVideoId}/make-vertical`, {
            method: 'POST'
        });
        if (res.ok) {
            showError('Vertical conversion started', false);
            startJobMonitor();
        }
    } catch (e) { showError('Vertical conversion failed'); }
}
// --- Remote Browser Logic ---
let socket = null;
let browserInitialized = false;

function initSocket() {
    if (socket) return;
    socket = io();

    socket.on('connect', () => {
        console.log('Socket connected');
        if (currentView === 'browser') startRemoteBrowser();
    });

    socket.on('browser_frame', (data) => {
        const img = document.getElementById('browserScreen');
        if (img) {
            img.src = 'data:image/jpeg;base64,' + data.image;
            // Hide loading overlay if any
            const overlay = document.getElementById('browserLoadingOverlay');
            if (overlay) overlay.style.display = 'none';
        }
    });

    socket.on('browser_status', (data) => {
        const statusEl = document.getElementById('browserStatus');
        if (!statusEl) return;

        if (data.status === 'loading') {
            statusEl.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Loading ${data.url}...`;
            statusEl.style.color = 'var(--primary-color)';
        } else if (data.status === 'rendering') {
            statusEl.innerHTML = `<i class="fas fa-paint-brush"></i> Pre-rendering...`;
            statusEl.style.color = '#f59e0b';
        } else if (data.status === 'ready') {
            statusEl.innerHTML = `<i class="fas fa-check-circle"></i> Ready (Live)`;
            statusEl.style.color = '#10b981';
        } else if (data.status === 'error') {
            statusEl.innerHTML = `<i class="fas fa-exclamation-triangle"></i> Error: ${data.message}`;
            statusEl.style.color = 'var(--danger)';
        }
    });

    socket.on('browser_download_detected', (data) => {
        showDownloadModal(data.filename, data.url, data.id);
    });

    socket.on('browser_download_finished', (data) => {
        // High visibility alert
        showError(`Video Ready: ${data.filename}`, false);
        // If modal is open for this ID, update UI
        if (activeDownloadId === data.id) {
            const btn = document.querySelector('#downloadModal .btn-primary');
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Import Now';
                btn.classList.add('pulse'); // Visual cue (needs CSS or just different style)
            }
        }
    });

    socket.on('browser_status_update', (data) => {
        showError(data.message, data.type === 'error');
    });
}

function startRemoteBrowser() {
    if (!socket || !socket.connected) {
        initSocket();
        return;
    }

    const overlay = document.getElementById('browserLoadingOverlay');
    if (overlay) overlay.style.display = 'flex';
    const img = document.getElementById('browserScreen');
    if (img) img.src = '';

    const url = document.getElementById('browserUrlInput').value || 'https://www.google.com';
    socket.emit('browser_init', { url });

    // Populate project selector for browser
    const sel = document.getElementById('browserTargetProject');
    if (sel && sel.options.length === 0) {
        fetch('/api/projects').then(r => r.json()).then(projects => {
            projects.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = p.name;
                sel.appendChild(opt);
            });
        });
    }
}

let lastPointerSent = 0;
function handleBrowserMouse(e, type) {
    if (!socket || !socket.connected) return;

    // Throttle move events
    if (type === 'mousemove') {
        const now = performance.now();
        if (now - lastPointerSent < 16) return;
        lastPointerSent = now;
    }

    const rect = document.getElementById('browserInputOverlay').getBoundingClientRect();
    const x = (e.clientX - rect.left) * (1280 / rect.width);
    const y = (e.clientY - rect.top) * (720 / rect.height);

    socket.emit('browser_input', {
        type: type,
        x: Math.round(x),
        y: Math.round(y),
        button: e.button === 2 ? 'right' : 'left'
    });
}

// Global keyboard passthrough for browser view
document.addEventListener('keydown', (e) => {
    if (currentView !== 'browser') return;
    if (document.activeElement.tagName === 'INPUT') return;

    if (socket && socket.connected) {
        socket.emit('browser_input', { type: 'keydown', key: e.key });
        e.preventDefault();
    }
});

document.addEventListener('keyup', (e) => {
    if (currentView !== 'browser') return;
    if (document.activeElement.tagName === 'INPUT') return;

    if (socket && socket.connected) {
        socket.emit('browser_input', { type: 'keyup', key: e.key });
    }
});

function handleBrowserWheel(e) {
    if (currentView !== 'browser' || !socket) return;
    socket.emit('browser_input', { type: 'scroll', deltaY: e.deltaY });
}

function navigateBrowser() {
    const url = document.getElementById('browserUrlInput').value;
    if (socket) socket.emit('browser_init', { url });
}

function browserReload() {
    if (socket) socket.emit('browser_input', { type: 'reload' });
}

function browserBack() {
    if (socket) socket.emit('browser_input', { type: 'back' });
}

function browserDownloadCurrent() {
    const projectId = document.getElementById('browserTargetProject').value;
    if (!projectId) return showError('Please select a project first');
    if (socket) {
        socket.emit('browser_input', { type: 'download', project_id: projectId });
        showError('Download started from browser URL!', false);
    }
}

const oldSwitchView = switchView;
switchView = function (viewName) {
    // If we are leaving the browser view, stop the browser
    if (currentView === 'browser' && viewName !== 'browser') {
        if (socket && socket.connected) {
            socket.emit('browser_stop');
        }
    }

    oldSwitchView(viewName);

    if (viewName === 'browser') {
        initSocket();
        startRemoteBrowser();
    }
}


let activeDownloadUrl = null;
let activeDownloadId = null;

function showDownloadModal(filename, url, id) {
    activeDownloadUrl = url;
    activeDownloadId = id;
    document.getElementById('detectedFilename').textContent = filename;

    // Auto-populate projects if empty
    const sel = document.getElementById('detectTargetProject');
    if (sel && sel.options.length === 0) {
        fetch('/api/projects').then(r => r.json()).then(projects => {
            projects.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = p.name;
                sel.appendChild(opt);
            });
        });
    }

    const modal = document.getElementById('downloadModal');
    modal.style.display = 'flex';
    modal.style.background = 'transparent';
    modal.style.pointerEvents = 'none';
    modal.querySelector('.card').style.pointerEvents = 'auto';

    const btn = document.querySelector('#downloadModal .btn-primary');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Finishing Capture...';
    }
}

function closeDownloadModal() {
    document.getElementById('downloadModal').style.display = 'none';
    activeDownloadUrl = null;
    activeDownloadId = null;
}

function confirmImportDownload() {
    const projectId = document.getElementById('detectTargetProject').value;
    if (!projectId) return showError('Please select a project first');

    if (socket && socket.connected) {
        socket.emit('browser_input', {
            type: 'download',
            project_id: projectId,
            url: activeDownloadUrl,
            download_id: activeDownloadId
        });
        showError('Import started for detected file!', false);
        closeDownloadModal();
    }
}

async function openServerImportModal() {
    if (!currentProjectId) return showError('Open a project first');
    document.getElementById('serverImportModal').style.display = 'flex';
    const list = document.getElementById('server-staged-list');
    list.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center;">Scanning server...</td></tr>';

    try {
        const res = await fetch('/api/browser/staged');
        const files = await res.json();
        list.innerHTML = '';

        if (files.length === 0) {
            list.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:var(--text-muted);">No staged files found.</td></tr>';
            return;
        }

        files.forEach(f => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid #f0f0f0';
            const sizeMB = (f.size / (1024 * 1024)).toFixed(1);
            tr.innerHTML = `
                <td style="padding:12px; font-size:0.85rem; max-width:250px; overflow:hidden; text-overflow:ellipsis;" title="${f.name}">${f.name}</td>
                <td style="padding:12px; font-size:0.85rem; color:var(--text-muted);">${sizeMB} MB</td>
                <td style="padding:12px;">
                    <button class="btn btn-primary" style="padding:4px 12px; font-size:0.75rem;" onclick="importFileFromServer('${f.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}')">Import</button>
                </td>
            `;
            list.appendChild(tr);
        });
    } catch (e) { list.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:var(--danger);">Failed to load files</td></tr>'; }
}

function closeServerImportModal() {
    document.getElementById('serverImportModal').style.display = 'none';
}

async function importFileFromServer(path) {
    if (!currentProjectId) return;
    try {
        const res = await fetch('/api/import/server-file', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, project_id: currentProjectId })
        });
        if (res.ok) {
            showError('Recovery job started!', false);
            closeServerImportModal();
        }
    } catch (e) { showError('Failed to start recovery'); }
}
// --- Reel Mode Logic ---
let reelVideos = [];
let currentReelIndex = 0;

async function openReelView() {
    if (!currentProjectId) return;
    try {
        const res = await fetch(`/api/projects/${currentProjectId}/videos`);
        const videos = await res.json();

        // Prefer clips, but show all if no clips exist
        reelVideos = videos.filter(v => v.is_clip);
        if (reelVideos.length === 0) reelVideos = videos;

        if (reelVideos.length === 0) return showError('No videos to display in Reel Mode');

        currentReelIndex = 0;
        document.getElementById('reelModal').style.display = 'flex';
        renderReel(currentReelIndex);

        // Keyboard navigation
        window.__reelKeyListener = (e) => {
            if (e.key === 'ArrowDown') nextReel();
            if (e.key === 'ArrowUp') prevReel();
            if (e.key === 'Escape') closeReelView();
        };
        window.addEventListener('keydown', window.__reelKeyListener);

    } catch (e) { showError('Failed to load reel'); }
}

function renderReel(index) {
    const v = reelVideos[index];
    const videoEl = document.getElementById('reelVideo');
    const titleEl = document.getElementById('reelTitle');
    const subtitleEl = document.getElementById('reelSubtitle');
    const progressEl = document.getElementById('reelProgress');
    const dlBtn = document.getElementById('reelDownloadBtn');

    videoEl.src = `/api/stream/${v.project_id}/${v.filename}`;
    videoEl.play();

    titleEl.textContent = v.title || v.filename;
    subtitleEl.textContent = `${document.getElementById('current-project-title').textContent} • Clip ${index + 1}/${reelVideos.length}`;

    dlBtn.onclick = () => window.open(`/api/video/${v.project_id}/${v.filename}`, '_blank');

    videoEl.ontimeupdate = () => {
        const p = (videoEl.currentTime / videoEl.duration) * 100;
        progressEl.style.width = p + '%';
    };
}

function nextReel() {
    if (currentReelIndex < reelVideos.length - 1) {
        currentReelIndex++;
        renderReel(currentReelIndex);
    } else {
        showError('Last video reached', false);
    }
}

function prevReel() {
    if (currentReelIndex > 0) {
        currentReelIndex--;
        renderReel(currentReelIndex);
    }
}

function closeReelView() {
    const videoEl = document.getElementById('reelVideo');
    videoEl.pause();
    videoEl.src = '';
    document.getElementById('reelModal').style.display = 'none';
    window.removeEventListener('keydown', window.__reelKeyListener);
}
