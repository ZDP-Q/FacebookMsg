const alertEl = document.getElementById('monitor-alert');

function showAlert(msg, type = 'info') {
    alertEl.textContent = msg;
    alertEl.className = `alert alert-${type} visible`;
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
        setTimeout(() => location.reload(), 1000);
    } catch (e) {
        showAlert(e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = orig;
    }
}

async function toggleMonitorEnabled(id, currentEnabled, btn) {
    const newEnabled = !currentEnabled;
    try {
        const r = await fetch(`/api/monitors/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: newEnabled }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || '操作失败');
        showAlert(`监控已${newEnabled ? '启用' : '暂停'}，刷新中...`, 'success');
        setTimeout(() => location.reload(), 500);
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
    } catch (e) {
        showAlert(e.message, 'error');
    }
}

async function loadReplied(id) {
    const wrap = document.getElementById(`replied-table-${id}`);
    wrap.innerHTML = '<p class="text-xs text-muted">加载中...</p>';
    try {
        const r = await fetch(`/api/monitors/${id}/replied?limit=50`);
        if (!r.ok) throw new Error('获取失败');
        const rows = await r.json();
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
    } catch (e) {
        wrap.innerHTML = `<p class="text-xs text-danger">${e.message}</p>`;
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
