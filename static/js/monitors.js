const alertEl = document.getElementById('monitor-alert');
const REPLIED_CACHE_PREFIX = 'monitor-replied-v1:';
const POLL_INTERVAL_MS = 8000;
let monitorPollTimer = null;
const lastRunSnapshot = new Map();

function showAlert(msg, type = 'info') {
    alertEl.textContent = msg;
    alertEl.className = `alert alert-${type} visible`;
}

function getMonitorIds() {
    return Array.from(document.querySelectorAll('.monitor-card'))
        .map(card => {
            const raw = String(card.id || '').replace('mc-', '');
            const id = parseInt(raw, 10);
            return Number.isFinite(id) ? id : null;
        })
        .filter(id => id !== null);
}

function getRepliedCacheKey(id) {
    return `${REPLIED_CACHE_PREFIX}${id}`;
}

function readRepliedCache(id) {
    try {
        const raw = localStorage.getItem(getRepliedCacheKey(id));
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed?.rows) ? parsed.rows : null;
    } catch {
        return null;
    }
}

function writeRepliedCache(id, rows) {
    try {
        localStorage.setItem(getRepliedCacheKey(id), JSON.stringify({ rows, ts: Date.now() }));
    } catch {
        // Ignore cache write errors silently.
    }
}

function renderRepliedRows(id, rows) {
    const wrap = document.getElementById(`replied-table-${id}`);
    if (!wrap) return;
    if (!rows.length) {
        wrap.innerHTML = '<p class="text-xs text-muted">暂无回复记录。</p>';
        return;
    }

    wrap.innerHTML = `
        <table>
            <thead>
                <tr>
                    <th>评论者</th>
                    <th>评论内容</th>
                    <th>回复内容</th>
                    <th>回复时间</th>
                </tr>
            </thead>
            <tbody>
                ${rows.map(row => `
                    <tr>
                        <td>${escHtml(row.author_name || '-')}</td>
                        <td class="td-truncate">${escHtml(row.comment_message || '-')}</td>
                        <td class="td-truncate">${escHtml(row.reply_message || '-')}</td>
                        <td class="td-muted text-xs">${escHtml(row.replied_at || '-')}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

function toggleMonitorCard(id) {
    const card = document.getElementById(`mc-${id}`);
    card?.classList.toggle('expanded');
}

async function runMonitor(id, btn) {
    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = '执行中...';
    showAlert(`正在执行监控 #${id}...`, 'info');
    try {
        const r = await fetch(`/api/monitors/${id}/run`, { method: 'POST' });
        if (!r.ok) throw new Error((await r.json()).detail || '执行失败');
        const res = await r.json();
        const result = res.result || {};
        showAlert(`执行完成：回复 ${result.replied ?? 0} 条，跳过 ${result.skipped ?? 0} 条。`, 'success');
        await refreshMonitorCards();
        await loadReplied(id, { forceNetwork: true });
    } catch (e) {
        showAlert(e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = orig;
    }
}

async function toggleMonitorEnabled(id, btn) {
    const currentEnabled = btn.dataset.enabled === '1';
    const newEnabled = !currentEnabled;
    try {
        const r = await fetch(`/api/monitors/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: newEnabled }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || '操作失败');
        showAlert(`监控已${newEnabled ? '启用' : '暂停'}。`, 'success');
        await refreshMonitorCards();
    } catch (e) {
        showAlert(e.message, 'error');
    }
}
async function saveMonitor(id) {
    const interval = parseInt(document.getElementById(`interval-${id}`)?.value || '300', 10);

    try {
        const r = await fetch(`/api/monitors/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ interval_seconds: interval }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || '更新失败');
        showAlert('监控设置已更新。', 'success');
        await refreshMonitorCards();
    } catch (e) {
        showAlert(e.message, 'error');
    }
}


async function deleteMonitor(id) {
    if (!confirm(`确认删除监控 #${id}？该操作不会删除帖子和评论数据。`)) return;
    try {
        const r = await fetch(`/api/monitors/${id}`, { method: 'DELETE' });
        if (!r.ok) throw new Error((await r.json()).detail || '删除失败');
        document.getElementById(`mc-${id}`)?.remove();
        showAlert('监控已删除。', 'success');
        updateBatchBar();
    } catch (e) {
        showAlert(e.message, 'error');
    }
}

function getSelectedMonitorIds() {
    return Array.from(document.querySelectorAll('.monitor-checkbox:checked'))
        .map(cb => parseInt(cb.dataset.id, 10))
        .filter(id => !isNaN(id));
}

function updateBatchBar() {
    const selected = getSelectedMonitorIds();
    const btn = document.getElementById('btn-batch-delete');
    const countEl = document.getElementById('selected-count');
    if (btn && countEl) {
        if (selected.length > 0) {
            btn.style.display = 'inline-block';
            countEl.textContent = selected.length;
        } else {
            btn.style.display = 'none';
        }
    }
}

async function bulkDeleteMonitors() {
    const ids = getSelectedMonitorIds();
    if (!ids.length) return;
    if (!confirm(`确认批量删除选中的 ${ids.length} 个监控？`)) return;

    const btn = document.getElementById('btn-batch-delete');
    btn.disabled = true;
    btn.textContent = '删除中...';

    try {
        const r = await fetch('/api/monitors/bulk-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || '批量删除失败');
        const res = await r.json();
        showAlert(`成功批量删除 ${res.deleted_count} 个监控。`, 'success');
        setTimeout(() => location.reload(), 800);
    } catch (e) {
        showAlert(e.message, 'error');
        btn.disabled = false;
        btn.textContent = `批量删除 (${ids.length})`;
    }
}

async function loadReplied(id, options = {}) {
    const forceNetwork = Boolean(options.forceNetwork);
    const cached = readRepliedCache(id);
    if (cached && !forceNetwork) {
        renderRepliedRows(id, cached);
        return cached;
    }

    const wrap = document.getElementById(`replied-table-${id}`);
    if (!wrap) return [];
    wrap.innerHTML = '<p class="text-xs text-muted">加载中...</p>';
    try {
        const r = await fetch(`/api/monitors/${id}/replied?limit=50`);
        if (!r.ok) throw new Error('获取失败');
        const rows = await r.json();
        renderRepliedRows(id, rows);
        writeRepliedCache(id, rows);
        return rows;
    } catch (e) {
        wrap.innerHTML = `<p class="text-xs text-danger">${e.message}</p>`;
        return [];
    }
}

function applyMonitorState(monitor) {
    const id = monitor.id;

    const dot = document.getElementById(`dot-${id}`);
    if (dot) {
        dot.classList.toggle('active', Boolean(monitor.enabled));
        dot.classList.toggle('paused', !monitor.enabled);
    }

    const enabledBadge = document.getElementById(`badge-enabled-${id}`);
    if (enabledBadge) {
        enabledBadge.classList.toggle('badge-success', Boolean(monitor.enabled));
        enabledBadge.classList.toggle('badge-neutral', !monitor.enabled);
    }

    const enabledText = document.getElementById(`enabled-text-${id}`);
    if (enabledText) enabledText.textContent = monitor.enabled ? '监控中' : '已暂停';

    const intervalBadge = document.getElementById(`badge-interval-${id}`);
    if (intervalBadge) intervalBadge.textContent = `每 ${monitor.interval_seconds}s`;

    const intervalInput = document.getElementById(`interval-${id}`);
    if (intervalInput && document.activeElement !== intervalInput) {
        intervalInput.value = String(monitor.interval_seconds);
    }

    const enabledBtn = document.getElementById(`btn-enabled-${id}`);
    if (enabledBtn) {
        enabledBtn.dataset.enabled = monitor.enabled ? '1' : '0';
        enabledBtn.textContent = monitor.enabled ? '暂停' : '启用';
    }

    const lastRun = document.getElementById(`last-run-${id}`);
    if (lastRun) lastRun.textContent = monitor.last_run_at || '从未';

    const lastStatus = document.getElementById(`last-status-${id}`);
    if (lastStatus) lastStatus.textContent = monitor.last_run_status || '-';
}

async function refreshMonitorCards() {
    const ids = new Set(getMonitorIds());
    if (!ids.size) return;

    const r = await fetch('/api/monitors');
    if (!r.ok) throw new Error('刷新监控状态失败');

    const monitors = await r.json();
    for (const monitor of monitors) {
        if (!ids.has(monitor.id)) continue;

        const lastRunKey = `${monitor.last_run_at || ''}|${monitor.last_run_status || ''}`;
        const prev = lastRunSnapshot.get(monitor.id);
        applyMonitorState(monitor);
        if (prev !== undefined && prev !== lastRunKey) {
            await loadReplied(monitor.id, { forceNetwork: true });
        }
        lastRunSnapshot.set(monitor.id, lastRunKey);
    }
}

function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/* === Add monitor modal === */
const modal = document.getElementById('add-modal');

document.getElementById('btn-add-monitor')?.addEventListener('click', openModal);

async function openModal() {
    modal.classList.add('open');
    const sel = document.getElementById('new-post-select');
    sel.innerHTML = '<option value="">加载中...</option>';
    try {
        const r = await fetch('/api/posts');
        if (!r.ok) throw new Error('获取帖子列表失败');
        const posts = await r.json();
        sel.innerHTML = posts.map(p =>
            `<option value="${escHtml(p.id)}" ${p.has_monitor ? 'disabled' : ''}>
                ${escHtml((p.message || '（无内容）').slice(0, 60))}
                ${p.has_monitor ? ' [已监控]' : ''}
            </option>`
        ).join('');
        if (!posts.length) sel.innerHTML = '<option value="">暂无帖子，请先同步</option>';
    } catch (e) {
        sel.innerHTML = `<option value="">加载失败：${escHtml(e.message)}</option>`;
    }
}

function closeModal() {
    modal.classList.remove('open');
}

modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
});

document.getElementById('btn-create-monitor')?.addEventListener('click', async () => {
    const postId   = document.getElementById('new-post-select').value;
    const interval = parseInt(document.getElementById('new-interval').value || '300');
    if (!postId) { showAlert('请选择一个帖子。', 'warning'); return; }
    const btn = document.getElementById('btn-create-monitor');
    btn.disabled = true; btn.textContent = '创建中...';
    try {
        const r = await fetch('/api/monitors', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ post_id: postId, interval_seconds: interval }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || '创建失败');
        showAlert('监控创建成功，刷新中...', 'success');
        setTimeout(() => location.reload(), 600);
    } catch (e) {
        showAlert(e.message, 'error');
    } finally {
        btn.disabled = false; btn.textContent = '创建监控';
    }
});

async function loadActivePersona() {
    const badge = document.getElementById('active-persona-badge');
    if (!badge) return;
    try {
        const r = await fetch('/api/prompts');
        if (!r.ok) throw new Error('获取失败');
        const res = await r.json();
        const active = (res.data || []).find(p => p.is_active);
        if (active) {
            badge.textContent = active.filename;
            badge.className = 'badge badge-success';
        } else {
            badge.textContent = '未配置';
            badge.className = 'badge badge-neutral';
        }
    } catch (e) {
        badge.textContent = '获取失败';
        badge.className = 'badge badge-danger';
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    loadActivePersona();

    // Batch Actions Event Listeners
    document.getElementById('select-all-monitors')?.addEventListener('change', (e) => {
        const checked = e.target.checked;
        document.querySelectorAll('.monitor-checkbox').forEach(cb => {
            cb.checked = checked;
        });
        updateBatchBar();
    });

    document.getElementById('monitor-list')?.addEventListener('change', (e) => {
        if (e.target.classList.contains('monitor-checkbox')) {
            updateBatchBar();
        }
    });

    document.getElementById('btn-batch-delete')?.addEventListener('click', bulkDeleteMonitors);

    const ids = getMonitorIds();
    if (!ids.length) return;

    for (const id of ids) {
        const cached = readRepliedCache(id);
        if (cached) {
            renderRepliedRows(id, cached);
        }
    }

    await Promise.all(ids.map(id => loadReplied(id, { forceNetwork: true })));
    try {
        await refreshMonitorCards();
    } catch {
        // Ignore first refresh failure; polling will retry.
    }

    monitorPollTimer = window.setInterval(async () => {
        try {
            await refreshMonitorCards();
        } catch {
            // Keep polling even if one request fails.
        }
    }, POLL_INTERVAL_MS);
});
