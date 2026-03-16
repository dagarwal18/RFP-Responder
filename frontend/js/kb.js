const kbFile = document.getElementById('kbFile');
const kbUploadBtn = document.getElementById('kbUploadBtn');
const kbDropzone = document.getElementById('kbDropzone');
const kbFileInfo = document.getElementById('kbFileInfo');

function showKBFile(files) {
  if (files.length === 1) {
    document.getElementById('kbFileName').textContent = files[0].name;
    document.getElementById('kbFileSize').textContent = `(${formatSize(files[0].size)})`;
  } else {
    document.getElementById('kbFileName').textContent = `${files.length} files selected`;
    let totalSize = Array.from(files).reduce((acc, file) => acc + file.size, 0);
    document.getElementById('kbFileSize').textContent = `(${formatSize(totalSize)} total)`;
  }
  kbFileInfo.style.display = 'flex';
}

function hideKBFile() {
  kbFileInfo.style.display = 'none';
}

kbFile.addEventListener('change', () => {
  kbUploadBtn.disabled = !kbFile.files.length;
  if (kbFile.files.length) {
    showKBFile(kbFile.files);
    if (kbFile.files.length === 1) {
      kbDropzone.querySelector('.label').innerHTML =
        `<strong>${kbFile.files[0].name}</strong> selected`;
    } else {
      kbDropzone.querySelector('.label').innerHTML =
        `<strong>${kbFile.files.length} files</strong> selected`;
    }
  } else {
    hideKBFile();
  }
});

// Drag & drop
kbDropzone.addEventListener('dragover', e => { e.preventDefault(); kbDropzone.classList.add('drag-over'); });
kbDropzone.addEventListener('dragleave', () => kbDropzone.classList.remove('drag-over'));
kbDropzone.addEventListener('drop', e => {
  e.preventDefault(); kbDropzone.classList.remove('drag-over');
  if (e.dataTransfer.files.length) {
    kbFile.files = e.dataTransfer.files;
    kbFile.dispatchEvent(new Event('change'));
  }
});

// Upload — iterating over multiple files
kbUploadBtn.addEventListener('click', async () => {
  const files = Array.from(kbFile.files);
  if (!files.length) return;

  const typeBadge = document.getElementById('kbClassifiedType');
  typeBadge.style.display = 'none';

  kbUploadBtn.disabled = true;
  kbUploadBtn.innerHTML = '<span class="spinner"></span> Uploading…';

  // Pause background polling so it doesn't compete with the upload
  pausePolling();

  let successCount = 0;
  let failCount = 0;

  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    addLog('kbLog', `Uploading ${file.name} (${i + 1}/${files.length})…`, 'info');

    const form = new FormData();
    form.append('file', file);
    // No doc_type → backend auto-classifies

    try {
      const data = await apiFetch('/api/knowledge/upload', { method: 'POST', body: form });

      // Show auto-classified type badge ONLY for single uploads (it looks weird for batches)
      if (files.length === 1) {
        const classLabel = data.auto_classified ? `Auto: ${data.doc_type}` : data.doc_type;
        typeBadge.textContent = classLabel;
        typeBadge.className = `classified-badge type-${data.doc_type}`;
        typeBadge.style.display = 'inline-block';
      }

      addLog('kbLog', `✓ ${file.name}: ${data.message}`, 'success');
      if (data.auto_classified) {
        addLog('kbLog', `📋 ${file.name} classified as "${data.doc_type}"`, 'info');
      }
      successCount++;
    } catch (e) {
      addLog('kbLog', `✗ Upload failed for ${file.name}: ${e.message}`, 'error');
      failCount++;
    }
  }

  // Refresh final stats & UI state
  if (files.length > 1) {
    addLog('kbLog', `Batch upload complete! ${successCount} succeeded, ${failCount} failed.`, 'info');
  }

  try {
    await loadKBStats();
    await loadKBFiles();
  } finally {
    kbUploadBtn.innerHTML = 'Upload to KB';
    kbUploadBtn.disabled = false;
    kbFile.value = '';
    kbDropzone.querySelector('.label').innerHTML =
      'Drop company docs or <strong>click to browse</strong>';
    hideKBFile();
    resumePolling();
  }
});

// Seed
async function loadKBStats() {
  try {
    const data = await apiFetch('/api/knowledge/status');
    document.getElementById('kbVectors').textContent = data.pinecone.total_vectors ?? '—';
    const nsCount = data.pinecone.namespaces ? Object.keys(data.pinecone.namespaces).length : 0;
    document.getElementById('kbNamespaces').textContent = nsCount;
    document.getElementById('kbConfigs').textContent =
      data.mongodb.configs ? data.mongodb.configs.length : 0;
    document.getElementById('kbBadge').textContent =
      `${data.pinecone.total_vectors ?? 0} vectors`;
  } catch {
    document.getElementById('kbBadge').textContent = 'Offline';
  }
}

// Query — with optional doc_type filter
async function loadKBFiles() {
  try {
    const files = await apiFetch('/api/knowledge/files');
    const box = document.getElementById('kbFilesList');
    if (!files.length) {
      box.innerHTML = '<div style="padding:8px;color:var(--text-muted);font-size:12px">No uploads yet.</div>';
      return;
    }
    box.innerHTML = files.map(f => {
      const autoTag = f.auto_classified ? ' (auto)' : '';
      return `
        <div class="kb-file-item">
          <span class="kb-file-name" title="${f.filename}">📄 ${f.filename}</span>
          <div class="kb-file-meta">
            <span class="kb-file-chunks">${f.chunks_stored} chunks</span>
            <span class="type-badge type-${f.doc_type}">${f.doc_type}${autoTag}</span>
          </div>
        </div>
      `;
    }).join('');
  } catch {
    // silently ignore
  }
}

