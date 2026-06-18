// ========== CONSTANTS ==========
const API = '';

// ========== AUTH LOGIC ==========
function getUsers() {
    const raw = localStorage.getItem('gdal_users');
    return raw ? JSON.parse(raw) : [];
}

function saveUsers(users) {
    localStorage.setItem('gdal_users', JSON.stringify(users));
}

function setSession(user) {
    localStorage.setItem('gdal_session', JSON.stringify(user));
}

function getSession() {
    const raw = localStorage.getItem('gdal_session');
    return raw ? JSON.parse(raw) : null;
}

function clearSession() {
    localStorage.removeItem('gdal_session');
}

// On page load
document.addEventListener('DOMContentLoaded', () => {
    const session = getSession();
    if (session) {
        showDashboard(session);
    } else {
        showAuth();
    }

    // Setup drag & drop
    const zone = document.getElementById('upload-zone');
    if (zone) {
        zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
        zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                handleFileUpload({ files: e.dataTransfer.files });
            }
        });
    }
});

function switchTab(tab) {
    const loginForm = document.getElementById('login-form');
    const signupForm = document.getElementById('signup-form');
    const tabLogin = document.getElementById('tab-login');
    const tabSignup = document.getElementById('tab-signup');
    const errDiv = document.getElementById('auth-error');

    errDiv.classList.remove('show');
    errDiv.textContent = '';

    if (tab === 'login') {
        loginForm.style.display = 'block';
        signupForm.style.display = 'none';
        tabLogin.classList.add('active');
        tabSignup.classList.remove('active');
    } else {
        loginForm.style.display = 'none';
        signupForm.style.display = 'block';
        tabLogin.classList.remove('active');
        tabSignup.classList.add('active');
    }
}

function showAuthError(msg) {
    const errDiv = document.getElementById('auth-error');
    errDiv.textContent = msg;
    errDiv.classList.add('show');
}

function handleSignup(e) {
    e.preventDefault();
    const name = document.getElementById('signup-name').value.trim();
    const email = document.getElementById('signup-email').value.trim().toLowerCase();
    const password = document.getElementById('signup-password').value;
    const confirm = document.getElementById('signup-confirm').value;

    if (password !== confirm) {
        showAuthError('Passwords do not match!');
        return;
    }
    if (password.length < 6) {
        showAuthError('Password must be at least 6 characters!');
        return;
    }

    const users = getUsers();
    if (users.find(u => u.email === email)) {
        showAuthError('An account with this email already exists!');
        return;
    }

    const newUser = { name, email, password, createdAt: new Date().toISOString() };
    users.push(newUser);
    saveUsers(users);

    showToast('Account created successfully! Please sign in.', 'success');
    switchTab('login');
    document.getElementById('login-email').value = email;
}

function handleLogin(e) {
    e.preventDefault();
    const email = document.getElementById('login-email').value.trim().toLowerCase();
    const password = document.getElementById('login-password').value;

    const users = getUsers();
    const user = users.find(u => u.email === email && u.password === password);

    if (!user) {
        showAuthError('Invalid email or password!');
        return;
    }

    setSession(user);
    showDashboard(user);
    showToast(`Welcome back, ${user.name}!`, 'success');
}

function handleLogout() {
    clearSession();
    showAuth();
    showToast('You have been logged out.', 'info');
}

function showAuth() {
    document.getElementById('auth-page').style.display = 'flex';
    document.getElementById('dashboard-page').style.display = 'none';
}

function showDashboard(user) {
    document.getElementById('auth-page').style.display = 'none';
    document.getElementById('dashboard-page').style.display = 'block';

    // Set user info
    document.getElementById('user-display-name').textContent = user.name;
    document.getElementById('user-avatar').textContent = user.name.charAt(0).toUpperCase();

    // Load initial data
    loadSupportedConversions();
}

// ========== NAVIGATION ==========
const sectionTitles = {
    'dashboard':     { title: 'Dashboard',            subtitle: 'Overview of your GIS processing' },
    'files-upload':  { title: 'Upload Files',          subtitle: 'Upload GIS files for processing' },
    'files-browse':  { title: 'Browse Files',          subtitle: 'View and manage uploaded files' },
    'files-remote':  { title: 'Remote Ingest',         subtitle: 'Import files from a remote URL' },
    'validation':    { title: 'Validation',            subtitle: 'Validate your GIS data files' },
    'workflows':     { title: 'Workflows',             subtitle: 'Manage and run processing workflows' },
    'jobs':          { title: 'Jobs',                  subtitle: 'Track and manage processing jobs' },
    'convert':       { title: 'Convert',               subtitle: 'Convert between GIS formats' },
    'preview':       { title: 'Preview Data',          subtitle: 'Preview job output data' },
    'outputs':       { title: 'Downloads',             subtitle: 'Download processed outputs' },
    'dispatched':    { title: 'Dispatched Layers',     subtitle: 'Manage dispatched output layers' },
    'credentials':   { title: 'Destination Credentials', subtitle: 'Manage storage credentials' },
    'admin':         { title: 'Admin',                 subtitle: 'System stats and audit logs' },
};

function navigateTo(section) {
    // Hide all panels
    document.querySelectorAll('.section-panel').forEach(p => p.classList.remove('active'));
    // Show target panel
    const panel = document.getElementById('section-' + section);
    if (panel) panel.classList.add('active');

    // Update nav items
    document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
    const navItem = document.querySelector(`.nav-item[data-section="${section}"]`);
    if (navItem) navItem.classList.add('active');

    // Update header
    const info = sectionTitles[section] || { title: section, subtitle: '' };
    document.getElementById('page-title').textContent = info.title;
    document.getElementById('page-subtitle').textContent = info.subtitle;

    // Auto-load data for specific sections
    if (section === 'dispatched') {
        loadDispatchedLayers();
    }
}

// ========== TOAST ==========
function showToast(msg, type = 'info') {
    const toast = document.getElementById('toast');
    const icons = { success: '✅', error: '❌', info: 'ℹ️' };
    document.getElementById('toast-icon').textContent = icons[type] || 'ℹ️';
    document.getElementById('toast-msg').textContent = msg;
    toast.className = 'toast ' + type + ' show';
    setTimeout(() => toast.classList.remove('show'), 3500);
}

// ========== API HELPERS ==========
async function apiGet(url) {
    try {
        const res = await fetch(API + url);
        return await res.json();
    } catch (err) {
        showToast('API Error: ' + err.message, 'error');
        return { error: err.message };
    }
}

async function apiPost(url, body) {
    try {
        const res = await fetch(API + url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        return await res.json();
    } catch (err) {
        showToast('API Error: ' + err.message, 'error');
        return { error: err.message };
    }
}

async function apiDelete(url) {
    try {
        const res = await fetch(API + url, { method: 'DELETE' });
        return await res.json();
    } catch (err) {
        showToast('API Error: ' + err.message, 'error');
        return { error: err.message };
    }
}

function showResult(elementId, data) {
    const el = document.getElementById(elementId);
    el.style.display = 'block';
    el.textContent = JSON.stringify(data, null, 2);
}

// ========== DASHBOARD ==========
async function loadHealth() {
    const data = await apiGet('/health');
    showResult('health-output', data);
    showToast('Health check completed', 'success');
}

async function loadSupportedConversions() {
    const data = await apiGet('/supported-conversions');
    showResult('conversions-output', data);
}

// ========== FILES ==========
async function handleFileUpload(input) {
    const file = input.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    const desc = document.getElementById('upload-description').value;
    if (desc) formData.append('description', desc);

    try {
        showToast('Uploading ' + file.name + '...', 'info');
        const res = await fetch(API + '/api/v1/files/upload', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        showResult('upload-result', data);
        showToast('File uploaded successfully!', 'success');
    } catch (err) {
        showToast('Upload failed: ' + err.message, 'error');
    }
}

async function getFileById() {
    const id = document.getElementById('browse-file-id').value.trim();
    if (!id) { showToast('Please enter a File ID', 'error'); return; }
    const data = await apiGet('/api/v1/files/' + id);
    showResult('file-browse-result', data);
}

async function getFileMetadata() {
    const id = document.getElementById('browse-file-id').value.trim();
    if (!id) { showToast('Please enter a File ID', 'error'); return; }
    const data = await apiGet('/api/v1/files/' + id + '/metadata');
    showResult('file-browse-result', data);
}

async function deleteFileById() {
    const id = document.getElementById('browse-file-id').value.trim();
    if (!id) { showToast('Please enter a File ID', 'error'); return; }
    if (!confirm('Are you sure you want to delete this file?')) return;
    const data = await apiDelete('/api/v1/files/' + id);
    showResult('file-browse-result', data);
    showToast('File deleted', 'success');
}

// ========== REMOTE INGEST ==========
async function ingestRemote() {
    const url = document.getElementById('remote-url').value.trim();
    if (!url) { showToast('Please enter a URL', 'error'); return; }
    const filename = document.getElementById('remote-filename').value.trim() || null;
    const data = await apiPost('/api/v1/files/ingest-remote', { url, filename });
    showResult('remote-result', data);
    showToast('Remote ingest initiated', 'success');
}

// ========== VALIDATION ==========
async function validateFile() {
    const id = document.getElementById('validate-file-id').value.trim();
    if (!id) { showToast('Please enter a File ID', 'error'); return; }
    const data = await apiPost('/api/v1/files/' + id + '/validate', { details: {} });
    showResult('validation-result', data);
    showToast('Validation started', 'success');
}

async function getValidationResult() {
    const id = document.getElementById('validate-file-id').value.trim();
    if (!id) { showToast('Please enter a File ID', 'error'); return; }
    const data = await apiGet('/api/v1/files/' + id + '/validation-result');
    showResult('validation-result', data);
}

// ========== WORKFLOWS ==========
async function loadWorkflows() {
    const data = await apiGet('/api/v1/workflows');
    showResult('workflows-list', data);
}

async function runWorkflow() {
    const code = document.getElementById('workflow-code').value.trim();
    if (!code) { showToast('Please enter a workflow code', 'error'); return; }
    let params = {};
    try {
        const raw = document.getElementById('workflow-params').value.trim();
        if (raw) params = JSON.parse(raw);
    } catch { showToast('Invalid JSON in parameters', 'error'); return; }
    const data = await apiPost('/api/v1/workflows/' + code + '/run', { parameters: params });
    showResult('workflow-result', data);
    showToast('Workflow started', 'success');
}

// ========== JOBS ==========
async function loadJobs() {
    const status = document.getElementById('jobs-status-filter').value;
    let url = '/api/v1/jobs';
    if (status) url += '?status=' + status;
    const data = await apiGet(url);
    showResult('jobs-list', data);
}

async function getJob() {
    const id = document.getElementById('job-action-id').value.trim();
    if (!id) { showToast('Please enter a Job ID', 'error'); return; }
    const data = await apiGet('/api/v1/jobs/' + id);
    showResult('job-action-result', data);
}

async function getJobLogs() {
    const id = document.getElementById('job-action-id').value.trim();
    if (!id) { showToast('Please enter a Job ID', 'error'); return; }
    const data = await apiGet('/api/v1/jobs/' + id + '/logs');
    showResult('job-action-result', data);
}

async function cancelJob() {
    const id = document.getElementById('job-action-id').value.trim();
    if (!id) { showToast('Please enter a Job ID', 'error'); return; }
    const data = await apiPost('/api/v1/jobs/' + id + '/cancel', { details: {} });
    showResult('job-action-result', data);
    showToast('Job cancelled', 'success');
}

async function retryJob() {
    const id = document.getElementById('job-action-id').value.trim();
    if (!id) { showToast('Please enter a Job ID', 'error'); return; }
    const data = await apiPost('/api/v1/jobs/' + id + '/retry', { details: {} });
    showResult('job-action-result', data);
    showToast('Job retried', 'success');
}

async function confirmPreview() {
    const id = document.getElementById('job-action-id').value.trim();
    if (!id) { showToast('Please enter a Job ID', 'error'); return; }
    const data = await apiPost('/api/v1/jobs/' + id + '/confirm-preview', { details: {} });
    showResult('job-action-result', data);
    showToast('Preview confirmed', 'success');
}

async function abortPreview() {
    const id = document.getElementById('job-action-id').value.trim();
    if (!id) { showToast('Please enter a Job ID', 'error'); return; }
    const data = await apiPost('/api/v1/jobs/' + id + '/abort-after-preview', { details: {} });
    showResult('job-action-result', data);
    showToast('Preview aborted', 'info');
}

// ========== CONVERT ==========
async function runConvert() {
    const body = {
        task_id: document.getElementById('convert-task-id').value.trim(),
        input_path: document.getElementById('convert-input-path').value.trim(),
        input_driver: document.getElementById('convert-input-driver').value.trim(),
        input_driver_ext: document.getElementById('convert-input-ext').value.trim(),
        conversion_driver: document.getElementById('convert-output-driver').value.trim(),
        conversion_driver_ext: document.getElementById('convert-output-ext').value.trim(),
        callback_url: document.getElementById('convert-callback').value.trim() || null,
        conversion_kwargs: {}
    };
    if (!body.task_id || !body.input_path) {
        showToast('Task ID and Input Path are required', 'error');
        return;
    }
    const data = await apiPost('/convert', body);
    showResult('convert-result', data);
    showToast('Conversion started!', 'success');
}

// ========== PREVIEW ==========
async function previewSummary() {
    const id = document.getElementById('preview-job-id').value.trim();
    if (!id) { showToast('Please enter a Job ID', 'error'); return; }
    const data = await apiGet('/api/v1/jobs/' + id + '/preview/summary');
    showResult('preview-result', data);
}

async function previewFeatures() {
    const id = document.getElementById('preview-job-id').value.trim();
    if (!id) { showToast('Please enter a Job ID', 'error'); return; }
    const data = await apiGet('/api/v1/jobs/' + id + '/preview/features');
    showResult('preview-result', data);
}

async function previewAttributes() {
    const id = document.getElementById('preview-job-id').value.trim();
    if (!id) { showToast('Please enter a Job ID', 'error'); return; }
    const data = await apiGet('/api/v1/jobs/' + id + '/preview/attributes');
    showResult('preview-result', data);
}

// ========== OUTPUTS ==========
function downloadOutput() {
    const id = document.getElementById('output-id').value.trim();
    if (!id) { showToast('Please enter an Output ID', 'error'); return; }
    window.open(API + '/api/v1/outputs/' + id + '/download', '_blank');
}

function downloadByTask() {
    const id = document.getElementById('download-task-id').value.trim();
    if (!id) { showToast('Please enter a Task ID', 'error'); return; }
    window.open(API + '/download/' + id, '_blank');
}

// ========== DISPATCHED LAYERS ==========
async function loadDispatchedLayers() {
    const data = await apiGet('/api/v1/dispatched-layers');
    const container = document.getElementById('dispatched-list');
    
    if (data.error) {
        container.innerHTML = `<div style="color: red; padding: 10px;">Error: ${data.error}</div>`;
        return;
    }
    
    if (!data.layers || data.layers.length === 0) {
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">No dispatched layers recorded.</div>';
        return;
    }
    
    let html = `
        <table style="width: 100%; border-collapse: collapse; text-align: left;">
            <thead>
                <tr style="border-bottom: 2px solid var(--border); font-weight: bold; color: var(--text-muted);">
                    <th style="padding: 10px;">Target Layer ID</th>
                    <th style="padding: 10px;">Target System</th>
                    <th style="padding: 10px;">Layer Name</th>
                    <th style="padding: 10px;">Geometry Type</th>
                    <th style="padding: 10px;">Features</th>
                    <th style="padding: 10px;">Job</th>
                    <th style="padding: 10px;">Input File</th>
                    <th style="padding: 10px;">Output File</th>
                    <th style="padding: 10px;">Status</th>
                    <th style="padding: 10px;">Dispatched At</th>
                    <th style="padding: 10px;">Actions</th>
                </tr>
            </thead>
            <tbody>
    `;
    
    data.layers.forEach(layer => {
        const statusColor = layer.status === 'success' || layer.status === 'confirmed' ? '#10b981' :
                           layer.status === 'failed' ? '#ef4444' :
                           layer.status === 'dispatched' ? '#3b82f6' :
                           layer.status === 'discovered' ? '#8b5cf6' : '#f59e0b';
        
        html += `
            <tr style="border-bottom: 1px solid var(--border);">
                <td style="padding: 10px; font-weight: 500;">${layer.target_layer_id || layer.id || 'N/A'}</td>
                <td style="padding: 10px;">${layer.target_system || 'N/A'}</td>
                <td style="padding: 10px;">${layer.layer_name || 'N/A'}</td>
                <td style="padding: 10px;">${layer.geometry_type || 'N/A'}</td>
                <td style="padding: 10px;">${layer.feature_count || 0}</td>
                <td style="padding: 10px;">${layer.job_id || 'N/A'}</td>
                <td style="padding: 10px;">${layer.input_format || 'N/A'}</td>
                <td style="padding: 10px;">${layer.output_format || 'N/A'} (${layer.output_files_count || 0} files)</td>
                <td style="padding: 10px;">
                    <span style="padding: 2px 8px; border-radius: 4px; font-size: 0.85em; font-weight: bold; color: white; background: ${statusColor};">
                        ${layer.status ? layer.status.toUpperCase() : 'UNKNOWN'}
                    </span>
                </td>
                <td style="padding: 10px; font-size: 0.85em; color: var(--text-muted);">${layer.dispatched_at || layer.created_at || 'N/A'}</td>
                <td style="padding: 10px;">
                    <button onclick="downloadDispatchedLayer('${layer.target_layer_id || layer.id}')" class="btn-secondary" style="font-size: 0.8em; padding: 4px 8px; margin: 0;">Download</button>
                </td>
            </tr>
        `;
    });
    
    html += '</tbody></table>';
    container.innerHTML = html;
    container.style.display = 'block';
}

async function downloadDispatchedLayer(layerId) {
    if (!layerId) { showToast('Invalid Layer ID', 'error'); return; }
    window.open(API + '/download/' + layerId, '_blank');
}

async function getDispatchedLayer() {
    const id = document.getElementById('dispatched-layer-id').value.trim();
    if (!id) { showToast('Please enter a Layer ID', 'error'); return; }
    const data = await apiGet('/api/v1/dispatched-layers/' + id);
    showResult('dispatched-result', data);
}

async function redispatchLayer() {
    const id = document.getElementById('dispatched-layer-id').value.trim();
    if (!id) { showToast('Please enter a Layer ID', 'error'); return; }
    const data = await apiPost('/api/v1/dispatched-layers/' + id + '/redispatch', { details: {} });
    showResult('dispatched-result', data);
    showToast('Layer redispatched', 'success');
}

// ========== CREDENTIALS ==========
async function loadCredentials() {
    const data = await apiGet('/api/v1/destination-credentials');
    showResult('credentials-list', data);
}

async function createCredential() {
    const name = document.getElementById('cred-name').value.trim();
    const type = document.getElementById('cred-type').value;
    let config = {};
    try {
        const raw = document.getElementById('cred-config').value.trim();
        if (raw) config = JSON.parse(raw);
    } catch { showToast('Invalid JSON in config', 'error'); return; }

    if (!name) { showToast('Please enter a name', 'error'); return; }
    const data = await apiPost('/api/v1/destination-credentials', { name, type, config });
    showResult('cred-result', data);
    showToast('Credential created', 'success');
}

async function deleteCredential() {
    const id = document.getElementById('cred-delete-id').value.trim();
    if (!id) { showToast('Please enter a Credential ID', 'error'); return; }
    if (!confirm('Are you sure?')) return;
    const data = await apiDelete('/api/v1/destination-credentials/' + id);
    showResult('cred-result', data);
    showToast('Credential deleted', 'success');
}

// ========== ADMIN ==========
async function loadAdminStats() {
    const start = document.getElementById('admin-start-date').value || '';
    const end = document.getElementById('admin-end-date').value || '';
    let url = '/api/v1/admin/stats';
    const params = [];
    if (start) params.push('start_date=' + start);
    if (end) params.push('end_date=' + end);
    if (params.length) url += '?' + params.join('&');
    const data = await apiGet(url);
    showResult('admin-stats-result', data);
}

async function loadAdminAudit() {
    const data = await apiGet('/api/v1/admin/audit');
    showResult('admin-audit-result', data);
}
