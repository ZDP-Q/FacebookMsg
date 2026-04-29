// 拦截旧调用
window.loadAllQuickStats = function() {};
window.toggleInsights = function() {};
window.fetchInsights = function() {};

const alertEl = document.getElementById('comments-alert');
const progressContainer = document.getElementById('sync-progress-container');
const progressBar = document.getElementById('sync-progress-bar');
const progressStatus = document.getElementById('progress-status');
const progressPercent = document.getElementById('progress-percent');

function showAlert(msg, type = 'info') {
    if (!alertEl) return;
    alertEl.textContent = msg;
    alertEl.className = `alert alert-${type} visible`;
}

/* Progress Bar Controls */
function showProgress(status = "正在处理...") {
    if (progressContainer) progressContainer.style.display = 'block';
    updateProgress(0, status);
}

function updateProgress(percent, status) {
    if (progressBar) progressBar.style.width = `${percent}%`;
    if (progressPercent) progressPercent.textContent = `${percent}%`;
    if (status && progressStatus) progressStatus.textContent = status;
}

function hideProgress() {
    if (progressContainer) progressContainer.style.display = 'none';
}

/* UI Interaction Functions */
window.togglePost = async function(headerEl) {
    const card = headerEl.closest('.post-card');
    const postId = card.getAttribute('data-post-id');
    const isExpanding = !card.classList.contains('expanded');
    
    card.classList.toggle('expanded');
    
    if (isExpanding) {
        // 如果是展开且尚未加载评论，则加载
        const listEl = document.getElementById(`comment-list-${postId}`);
        if (listEl && listEl.getAttribute('data-loaded') !== 'true') {
            await loadComments(postId, listEl);
        }
    }
}

async function loadComments(postId, listEl) {
    try {
        const r = await fetch(`/api/posts/${postId}/comments`);
        if (!r.ok) throw new Error('加载评论失败');
        const comments = await r.json();
        
        if (!comments || comments.length === 0) {
            listEl.innerHTML = '<div class="empty-state" style="padding:20px"><p>该帖子暂无评论。</p></div>';
        } else {
            listEl.innerHTML = '';
            comments.forEach(c => renderComment(c, listEl, 0));
        }
        listEl.setAttribute('data-loaded', 'true');
    } catch (e) {
        listEl.innerHTML = `<div class="empty-state" style="padding:20px; color: var(--danger);"><p>${e.message}</p></div>`;
    }
}

function renderComment(comment, container, depth) {
    const item = document.createElement('div');
    item.className = `comment-item ${depth > 0 ? 'reply-item' : ''}`;
    item.id = `ci-${comment.id}`;
    if (depth > 0) item.style.marginLeft = `${depth * 20}px`;
    
    const avatarChar = (comment.author_name || '?')[0].toUpperCase();
    
    item.innerHTML = `
        <div class="comment-top">
            <div class="comment-avatar">${avatarChar}</div>
            <div class="comment-body">
                <span class="comment-author">${comment.author_name || '匿名用户'}</span>
                <span class="comment-time">${comment.created_time || ''}</span>
                <p class="comment-text">${comment.message || '（空）'}</p>
            </div>
        </div>
        <div class="comment-actions-row">
            <button class="btn btn-ghost btn-xs" onclick="toggleReplyForm('${comment.id}')">回复</button>
            <button class="btn btn-ghost btn-xs" onclick="genAiReply('${comment.id}', this)">AI 生成</button>
            <button class="btn btn-danger btn-xs" onclick="delComment('${comment.id}')">删除</button>
        </div>
        <div class="reply-form-wrap" id="rf-${comment.id}">
            <textarea id="rt-${comment.id}" placeholder="输入回复..."></textarea>
            <div class="reply-form-actions">
                <button class="btn btn-secondary btn-sm" onclick="toggleReplyForm('${comment.id}')">取消</button>
                <button class="btn btn-primary btn-sm" onclick="sendReply('${comment.id}')">发送</button>
            </div>
        </div>
    `;
    
    container.appendChild(item);
    
    if (comment.replies && comment.replies.length > 0) {
        comment.replies.forEach(reply => renderComment(reply, container, depth + 1));
    }
}

window.toggleReplyForm = function(commentId) {
    const form = document.getElementById(`rf-${commentId}`);
    if (form) form.classList.toggle('open');
}

window.sendReply = async function(commentId) {
    const ta = document.getElementById(`rt-${commentId}`);
    const msg = ta.value.trim();
    if (!msg) { showAlert('请输入回复内容', 'warning'); return; }
    showAlert('正在发送回复...', 'info');
    try {
        const r = await fetch(`/api/comments/${commentId}/reply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || '发送失败');
        showAlert('回复发送成功，正在刷新...', 'success');
        setTimeout(() => location.reload(), 600);
    } catch (e) {
        showAlert(e.message, 'error');
    }
}

window.genAiReply = async function(commentId, btn) {
    if (btn.disabled) return;
    const form = document.getElementById(`rf-${commentId}`);
    const ta = document.getElementById(`rt-${commentId}`);
    if (form) form.classList.add('open');
    if (ta) {
        ta.value = '';
        ta.placeholder = 'AI 生成中，请稍候...';
    }
    btn.disabled = true;
    const origText = btn.textContent;
    btn.textContent = '生成中...';
    showAlert('AI 正在生成回复...', 'info');
    try {
        const r = await fetch(`/api/comments/${commentId}/ai-reply`, { method: 'POST' });
        if (!r.ok) throw new Error((await r.json()).detail || '生成失败');
        const res = await r.json();
        if (ta) {
            ta.value = res.message;
            ta.placeholder = '输入回复内容...';
            ta.focus();
        }
        showAlert('AI 回复已生成，请确认后发送。', 'success');
    } catch (e) {
        if (ta) ta.placeholder = '输入回复内容...';
        showAlert(e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = origText;
    }
}

window.delComment = async function(commentId) {
    if (!confirm('确认删除这条评论？该操作会同步删除 Facebook 上的评论。')) return;
    showAlert('正在删除...', 'info');
    try {
        const r = await fetch(`/api/comments/${commentId}`, { method: 'DELETE' });
        if (!r.ok) throw new Error((await r.json()).detail || '删除失败');
        const el = document.getElementById(`ci-${commentId}`);
        if (el) el.remove();
        showAlert('删除成功。', 'success');
    } catch (e) {
        showAlert(e.message, 'error');
    }
}

window.syncPost = async function(postId, btn) {
    if (btn?.disabled) return;
    const original = btn?.textContent || '同步';
    if (btn) {
        btn.disabled = true;
        btn.textContent = '...';
    }
    showProgress(`正在同步帖子 ${postId}`);
    updateProgress(30, "正在连接 Facebook...");
    
    try {
        const r = await fetch(`/api/sync/posts/${encodeURIComponent(postId)}`, { method: 'POST' });
        if (!r.ok) throw new Error((await r.json()).detail || '同步失败');
        updateProgress(100, "同步完成！");
        showAlert('该帖子同步完成，刷新页面...', 'success');
        setTimeout(() => location.reload(), 600);
    } catch (e) {
        hideProgress();
        showAlert(e.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = original;
        }
    }
}

window.addMonitor = async function(postId, btn) {
    if (btn?.disabled) return;
    const original = btn?.textContent || '监控';
    if (btn) {
        btn.disabled = true;
        btn.textContent = '...';
    }
    showAlert('正在创建监控...', 'info');
    try {
        const r = await fetch('/api/monitors', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ post_id: postId, interval_seconds: 300 }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || '创建监控失败');
        
        // 更新 UI，不再刷新页面
        showAlert('监控创建成功。', 'success');
        if (btn) {
            btn.textContent = '已监控';
            btn.className = 'btn btn-ghost btn-xs';
            btn.style.color = 'var(--success)';
            btn.disabled = true;
            btn.onclick = null; // 移除点击事件
        }
    } catch (e) {
        showAlert(e.message, 'error');
        if (btn) {
            btn.disabled = false;
            btn.textContent = original;
        }
    }
}

async function doSync(limit, since, until, allPosts = false) {
    showAlert(`开始同步任务...`, 'info');
    showProgress("正在准备同步帖子...");
    
    const params = new URLSearchParams({ 
        limit: limit.toString(), 
        all_posts: allPosts.toString() 
    });
    if (since) params.append('since', since);
    if (until) params.append('until', until);
    
    const eventSource = new EventSource(`/api/sync/stream?${params.toString()}`);
    
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.error) {
            eventSource.close();
            hideProgress();
            showAlert(data.error, 'error');
            return;
        }
        
        if (data.percent !== undefined) {
            updateProgress(data.percent, data.status);
        }
        
        if (data.status === "completed") {
            eventSource.close();
            updateProgress(100, "同步成功！");
            showAlert('同步完成，正在刷新页面...', 'success');
            setTimeout(() => location.reload(), 800);
        }
    };
    
    eventSource.onerror = (e) => {
        eventSource.close();
        // 如果已经 100% 或者是 completed 状态，忽略错误
        if (progressPercent && progressPercent.textContent === "100%") return;
        hideProgress();
        showAlert("同步过程中连接中断，请重试。", 'error');
    };
}

function updateSelectedCount() {
    const checked = document.querySelectorAll('.post-checkbox:checked').length;
    const el = document.getElementById('selected-count');
    if (el) el.textContent = `已选中 ${checked} 篇`;
}

async function deletePosts(postIds) {
    if (!postIds.length) return;
    showProgress(`正在从本地删除 ${postIds.length} 篇帖子...`);
    updateProgress(50, "正在删除数据...");
    try {
        const r = await fetch('/api/posts/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ post_ids: postIds }),
        });
        if (!r.ok) throw new Error('操作失败');
        updateProgress(100, "删除成功！");
        showAlert('帖子已从本地数据库永久删除，正在刷新...', 'success');
        setTimeout(() => location.reload(), 600);
    } catch (e) {
        hideProgress();
        showAlert(e.message, 'error');
    }
}

window.deleteSinglePost = async function(postId) {
    if (confirm("确认从本地数据库永久删除该帖子及其所有评论？此操作不可撤销（除非重新同步）。")) {
        await deletePosts([postId]);
    }
}

/* Initialize everything after DOM load */
document.addEventListener('DOMContentLoaded', () => {
    // 1. 同步帖子 (筛选栏)
    document.getElementById('btn-sync-custom')?.addEventListener('click', () => {
        const limit = parseInt(document.getElementById('sync-limit')?.value || '20', 10);
        const since = document.getElementById('sync-since')?.value?.trim() || '';
        const until = document.getElementById('sync-until')?.value?.trim() || '';
        doSync(limit, since, until);
    });

    // 2. 同步全量评论
    document.getElementById('btn-sync-comments')?.addEventListener('click', async (e) => {
        doSync(0, "", "", true);
    });

    // 3. 全选
    document.getElementById('btn-select-all')?.addEventListener('click', () => {
        document.querySelectorAll('.post-checkbox').forEach(cb => cb.checked = true);
        updateSelectedCount();
    });

    // 4. 取消选择
    document.getElementById('btn-select-none')?.addEventListener('click', () => {
        document.querySelectorAll('.post-checkbox').forEach(cb => cb.checked = false);
        updateSelectedCount();
    });

    // 5. 删除选中
    document.getElementById('btn-delete-selected')?.addEventListener('click', async () => {
        const checkedCbs = document.querySelectorAll('.post-checkbox:checked');
        const ids = Array.from(checkedCbs).map(cb => cb.getAttribute('data-post-id'));
        if (!ids.length) {
            showAlert('请先勾选需要删除的帖子', 'warning');
            return;
        }
        if (confirm(`确认从本地数据库永久删除选中的 ${ids.length} 篇帖子吗？此操作不可撤销。`)) {
            await deletePosts(ids);
        }
    });

    // 6. 清空当前列表
    document.getElementById('btn-clear-all')?.addEventListener('click', async () => {
        if (!confirm('确认清空当前账号在本地数据库中的所有帖子和评论？此操作不可撤销。')) return;
        showProgress('正在清空本地数据...');
        try {
            const r = await fetch('/api/posts/clear-all', { method: 'POST' });
            if (!r.ok) throw new Error('操作失败');
            updateProgress(100, "清空成功！");
            showAlert('本地列表已清空，正在刷新...', 'success');
            setTimeout(() => location.reload(), 600);
        } catch (e) {
            hideProgress();
            showAlert(e.message, 'error');
        }
    });

    // 7. Checkbox Change event delegation
    document.querySelector('.posts-scroll')?.addEventListener('change', (e) => {
        if (e.target.classList.contains('post-checkbox')) {
            updateSelectedCount();
        }
    });
});
