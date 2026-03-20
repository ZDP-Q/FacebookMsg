const alertEl = document.getElementById('home-alert');

const METRIC_LABELS = {
    page_impressions: '主页触达 (28天)',
    page_media_view: '主页媒体浏览',
    page_total_media_view_unique: '主页媒体独立浏览',
    page_engaged_users: '互动用户数 (28天)',
    page_views_total: '主页浏览量 (28天)',
    page_post_engagements: '帖子互动',
    post_impressions: '帖子触达',
    post_media_view: '帖子媒体浏览',
    post_total_media_view_unique: '帖子媒体独立浏览',
    post_engaged_users: '帖子互动用户',
    total_video_views: '视频播放次数',
    total_video_view_total_time: '视频总观看时长',
    total_video_complete_views: '视频完整观看次数',
};

let settingsState = {
    accounts: [],
    activeAccountId: null,
    selectedAccountId: null,
};

function showAlert(msg, type = 'info') {
    alertEl.textContent = msg;
    alertEl.className = `alert alert-${type} visible`;
}

function fmtNum(v) {
    if (typeof v !== 'number') return String(v ?? '-');
    if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
    return v.toLocaleString('zh-CN');
}

function renderInsights(gridEl, metrics) {
    if (!metrics || metrics.length === 0) {
        gridEl.innerHTML = '<div class="stat-item"><div class="stat-label">暂无数据</div><div class="stat-value">-</div></div>';
        return;
    }
    gridEl.innerHTML = metrics.map((m) => {
        const latest = Array.isArray(m.values) ? m.values[0] : null;
        const val = latest ? fmtNum(latest.value) : '-';
        const label = METRIC_LABELS[m.name] || m.name;
        return `<div class="stat-item"><div class="stat-label">${label}</div><div class="stat-value">${val}</div></div>`;
    }).join('');
}

function getAccountFromForm() {
    return {
        name: (document.getElementById('account-name')?.value || '').trim(),
        page_id: (document.getElementById('account-page-id')?.value || '').trim(),
        api_version: (document.getElementById('account-api-version')?.value || '').trim() || 'v25.0',
        page_access_token: (document.getElementById('account-token')?.value || '').trim(),
        verify_token: (document.getElementById('account-verify-token')?.value || '').trim(),
    };
}

function fillAccountForm(account) {
    document.getElementById('account-name').value = account?.name || '';
    document.getElementById('account-page-id').value = account?.page_id || '';
    document.getElementById('account-api-version').value = account?.api_version || 'v25.0';
    document.getElementById('account-token').value = account?.page_access_token || '';
    document.getElementById('account-verify-token').value = account?.verify_token || '';
}

function renderAccountSelect() {
    const select = document.getElementById('account-select');
    const options = settingsState.accounts.map((a) => {
        const activeMark = Number(a.id) === Number(settingsState.activeAccountId) ? ' (当前)' : '';
        return `<option value="${a.id}">${a.name || `账号 ${a.page_id}`}${activeMark}</option>`;
    }).join('');
    select.innerHTML = options || '<option value="">暂无账号</option>';

    if (settingsState.selectedAccountId) {
        select.value = String(settingsState.selectedAccountId);
    } else if (settingsState.activeAccountId) {
        select.value = String(settingsState.activeAccountId);
    }

    if (select.value) {
        const account = settingsState.accounts.find((a) => Number(a.id) === Number(select.value));
        settingsState.selectedAccountId = Number(select.value);
        fillAccountForm(account);
    } else {
        fillAccountForm(null);
    }
}

async function loadSettings() {
    const r = await fetch('/api/settings');
    if (!r.ok) throw new Error('加载配置失败');
    const data = await r.json();

    settingsState.accounts = Array.isArray(data.accounts) ? data.accounts : [];
    settingsState.activeAccountId = data.active_account_id || null;
    if (!settingsState.selectedAccountId && settingsState.activeAccountId) {
        settingsState.selectedAccountId = Number(settingsState.activeAccountId);
    }
    renderAccountSelect();

    const model = data.model || {};
    document.getElementById('model-base-url').value = model.ai_api_base_url || '';
    document.getElementById('model-api-key').value = model.ai_api_key || '';
    document.getElementById('model-name').value = model.ai_model || '';
    document.getElementById('model-system-prompt').value = model.ai_system_prompt || '';
}

async function saveAccount() {
    const payload = getAccountFromForm();
    if (!payload.page_id || !payload.page_access_token || !payload.verify_token) {
        showAlert('请填写 PAGE_ID、PAGE_ACCESS_TOKEN、VERIFY_TOKEN。', 'warning');
        return;
    }

    const accountId = settingsState.selectedAccountId;
    const isUpdate = Boolean(accountId && settingsState.accounts.some((a) => Number(a.id) === Number(accountId)));
    const url = isUpdate ? `/api/settings/accounts/${accountId}` : '/api/settings/accounts';
    const method = isUpdate ? 'PUT' : 'POST';

    const r = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || '保存账号失败');
    }

    const result = await r.json().catch(() => ({}));
    if (!isUpdate && result.account_id) {
        settingsState.selectedAccountId = Number(result.account_id);
    }
}

async function loadProfile() {
    try {
        const r = await fetch('/api/page-profile');
        if (!r.ok) throw new Error((await r.json()).detail || '获取主页信息失败');
        const p = await r.json();
        document.getElementById('profile-name').textContent = p.name || '未命名';
        document.getElementById('profile-category').textContent = p.category || '-';
        document.getElementById('profile-username').textContent = p.username || '-';
        document.getElementById('profile-fans').textContent = p.fan_count ?? '-';
        const link = document.getElementById('profile-link');
        link.textContent = p.link || '-';
        link.href = p.link || '#';
        document.getElementById('profile-sync-time').textContent = `同步于 ${p.synced_at || '-'}`;
    } catch (e) {
        document.getElementById('profile-name').textContent = '-';
        document.getElementById('profile-category').textContent = '-';
        document.getElementById('profile-username').textContent = '-';
        document.getElementById('profile-fans').textContent = '-';
        const link = document.getElementById('profile-link');
        link.textContent = '-';
        link.href = '#';
        document.getElementById('profile-sync-time').textContent = '-';
        showAlert(e.message, 'warning');
    }
}

async function loadInsights() {
    const grid = document.getElementById('page-insights-grid');
    try {
        const r = await fetch('/api/insights/page');
        if (!r.ok) throw new Error('获取洞察数据失败');
        const result = await r.json();
        renderInsights(grid, result.data);
    } catch (e) {
        grid.innerHTML = `<div class="stat-item"><div class="stat-label text-danger">${e.message}</div><div class="stat-value">-</div></div>`;
    }
}

async function doSync(limit, since, until) {
    showAlert(`正在同步最多 ${limit} 条帖子...`, 'info');
    const btn = document.getElementById('btn-sync');
    if (btn) {
        btn.disabled = true;
        btn.textContent = '同步中...';
    }
    try {
        const params = new URLSearchParams({ limit });
        if (since) params.append('since', since);
        if (until) params.append('until', until);
        const r = await fetch(`/api/sync?${params}`, { method: 'POST' });
        if (!r.ok) throw new Error((await r.json()).detail || '同步失败');
        const res = await r.json();
        const s = res.summary || {};
        showAlert(`同步完成：${s.post_count} 篇帖子，${s.comment_count} 条评论。`, 'success');
        loadProfile();
    } catch (e) {
        showAlert(e.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = '立即同步';
        }
    }
}

document.getElementById('account-select')?.addEventListener('change', (e) => {
    settingsState.selectedAccountId = Number(e.target.value || 0) || null;
    const account = settingsState.accounts.find((a) => Number(a.id) === Number(settingsState.selectedAccountId));
    fillAccountForm(account || null);
});

document.getElementById('btn-account-new')?.addEventListener('click', () => {
    settingsState.selectedAccountId = null;
    const select = document.getElementById('account-select');
    if (select) select.value = '';
    fillAccountForm(null);
});

document.getElementById('btn-account-save')?.addEventListener('click', async () => {
    try {
        await saveAccount();
        await loadSettings();
        showAlert('账号配置已保存。', 'success');
    } catch (e) {
        showAlert(e.message, 'error');
    }
});

document.getElementById('btn-account-activate')?.addEventListener('click', async () => {
    if (!settingsState.selectedAccountId) {
        showAlert('请先选择一个账号。', 'warning');
        return;
    }
    try {
        const r = await fetch(`/api/settings/accounts/${settingsState.selectedAccountId}/activate`, { method: 'POST' });
        if (!r.ok) throw new Error((await r.json()).detail || '切换失败');
        showAlert('账号已切换，页面刷新中...', 'success');
        setTimeout(() => location.reload(), 500);
    } catch (e) {
        showAlert(e.message, 'error');
    }
});

document.getElementById('btn-account-delete')?.addEventListener('click', async () => {
    if (!settingsState.selectedAccountId) {
        showAlert('请先选择一个账号。', 'warning');
        return;
    }
    if (!confirm('确认删除该账号配置？')) return;
    try {
        const r = await fetch(`/api/settings/accounts/${settingsState.selectedAccountId}`, { method: 'DELETE' });
        if (!r.ok) throw new Error((await r.json()).detail || '删除失败');
        settingsState.selectedAccountId = null;
        await loadSettings();
        showAlert('账号已删除。', 'success');
        setTimeout(() => location.reload(), 400);
    } catch (e) {
        showAlert(e.message, 'error');
    }
});

document.getElementById('btn-model-save')?.addEventListener('click', async () => {
    const payload = {
        ai_api_base_url: (document.getElementById('model-base-url')?.value || '').trim(),
        ai_api_key: (document.getElementById('model-api-key')?.value || '').trim(),
        ai_model: (document.getElementById('model-name')?.value || '').trim(),
        ai_system_prompt: (document.getElementById('model-system-prompt')?.value || '').trim(),
    };

    try {
        const r = await fetch('/api/settings/model', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error((await r.json()).detail || '保存失败');
        showAlert('模型配置已保存。', 'success');
    } catch (e) {
        showAlert(e.message, 'error');
    }
});

document.getElementById('btn-model-test')?.addEventListener('click', async () => {
    const payload = {
        ai_api_base_url: (document.getElementById('model-base-url')?.value || '').trim(),
        ai_api_key: (document.getElementById('model-api-key')?.value || '').trim(),
        ai_model: (document.getElementById('model-name')?.value || '').trim(),
        ai_system_prompt: (document.getElementById('model-system-prompt')?.value || '').trim(),
    };

    const btn = document.getElementById('btn-model-test');
    btn.disabled = true;
    btn.textContent = '测试中...';
    showAlert('正在测试 AI 连接，请稍候...', 'info');

    try {
        const r = await fetch('/api/settings/model/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const res = await r.json();
        if (!r.ok) throw new Error(res.detail || '测试失败');
        showAlert(res.message || '连接成功！', 'success');
    } catch (e) {
        showAlert(e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '测试配置';
    }
});

document.getElementById('btn-change-password')?.addEventListener('click', async () => {
    const oldPassword = (document.getElementById('admin-old-password')?.value || '').trim();
    const newPassword = (document.getElementById('admin-new-password')?.value || '').trim();

    if (!oldPassword || !newPassword) {
        showAlert('请填写当前密码与新密码。', 'warning');
        return;
    }

    try {
        const r = await fetch('/api/admin/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || '密码更新失败');

        showAlert('密码已更新，请重新登录。', 'success');
        setTimeout(() => {
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/logout';
            document.body.appendChild(form);
            form.submit();
        }, 500);
    } catch (e) {
        showAlert(e.message, 'error');
    }
});

document.getElementById('btn-sync')?.addEventListener('click', () => doSync(20, '', ''));

document.getElementById('btn-sync-custom')?.addEventListener('click', () => {
    const limit = parseInt(document.getElementById('sync-limit')?.value || '20', 10);
    const since = document.getElementById('sync-since')?.value?.trim() || '';
    const until = document.getElementById('sync-until')?.value?.trim() || '';
    doSync(limit, since, until);
});

document.getElementById('btn-sync-insights')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-sync-insights');
    btn.disabled = true;
    btn.textContent = '同步中...';
    showAlert('正在同步洞察数据...', 'info');
    try {
        const r = await fetch('/api/sync-insights', { method: 'POST' });
        if (!r.ok) throw new Error((await r.json()).detail || '同步失败');
        const res = await r.json();
        const s = res.summary || {};
        showAlert(`洞察同步完成：页面指标 ${s.page_metrics ?? '-'} 项，帖子 ${s.posts_synced ?? '-'} 篇。`, 'success');
        loadInsights();
    } catch (e) {
        showAlert(e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '同步洞察数据';
    }
});

document.getElementById('btn-refresh-insights')?.addEventListener('click', loadInsights);

(async function init() {
    try {
        await loadSettings();
    } catch (e) {
        showAlert(e.message, 'error');
    }
    await loadProfile();
    await loadInsights();
})();
