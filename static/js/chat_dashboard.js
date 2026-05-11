const alertEl = document.getElementById('chat-alert');

function showAlert(msg, type = 'info') {
    alertEl.textContent = msg;
    alertEl.className = `alert alert-${type} visible`;
}

async function loadDashboard() {
    try {
        const r = await fetch('/api/chats/stats');
        if (!r.ok) throw new Error('获取统计数据失败');
        const data = await r.json();
        
        // 1. Update Top Hero Stats
        const s = data.stats;
        document.getElementById('stat-total-users').textContent = (s.total_users || 0).toLocaleString();
        document.getElementById('stat-total-messages').textContent = (s.total_messages || 0).toLocaleString();
        document.getElementById('stat-longest-msg').textContent = (s.longest_msg_count || 0).toLocaleString();
        document.getElementById('stat-longest-duration').textContent = (s.longest_duration_days || 0) + 'd';
        document.getElementById('stat-max-streak').textContent = (s.max_streak || 0) + 'd';
        
        // 2. Update Detailed Distribution Stats
        if (data.detailed_stats) {
            updateDetailedStats(data.detailed_stats);
        }
    } catch (e) {
        showAlert(e.message, 'error');
    }
}

function updateDetailedStats(detailed) {
    // Message Stats per user
    document.getElementById('msg-max').textContent = detailed.messages.max.toLocaleString();
    document.getElementById('msg-min').textContent = detailed.messages.min.toLocaleString();
    document.getElementById('msg-avg').textContent = detailed.messages.avg.toLocaleString();
    document.getElementById('msg-median').textContent = detailed.messages.median.toLocaleString();
    document.getElementById('msg-p99').textContent = detailed.messages.p99.toLocaleString();
    document.getElementById('msg-p95').textContent = detailed.messages.p95.toLocaleString();
    document.getElementById('msg-p90').textContent = detailed.messages.p90.toLocaleString();
    document.getElementById('msg-p80').textContent = detailed.messages.p80.toLocaleString();

    // Total Active Days Distribution
    if (detailed.active_days_dist) {
        const d = detailed.active_days_dist;
        document.getElementById('active-days-max').textContent = d.max + ' 天';
        document.getElementById('active-days-avg').textContent = d.avg + ' 天';
        document.getElementById('active-days-median').textContent = d.median + ' 天';
        document.getElementById('active-days-p99').textContent = d.p99 + ' 天';
        document.getElementById('active-days-p95').textContent = d.p95 + ' 天';
        document.getElementById('active-days-p90').textContent = d.p90 + ' 天';
        document.getElementById('active-days-p80').textContent = d.p80 + ' 天';
    }

    // Tiered Streak Stats
    const body = document.getElementById('streak-tiered-body');
    body.innerHTML = '';
    
    const labels = {
        'all': '全部用户 (All)',
        'p80': 'Top 20% (P80)',
        'p90': 'Top 10% (P90)',
        'p95': 'Top 5% (P95)',
        'p99': 'Top 1% (P99)'
    };
    
    // Sort keys to show All then P80 down to P99 (or vice versa, let's do All -> P80 -> P90 -> P95 -> P99)
    ['all', 'p80', 'p90', 'p95', 'p99'].forEach(key => {
        if (detailed.streaks[key]) {
            const s = detailed.streaks[key];
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <th>${labels[key]}</th>
                <td class="stat-highlight">${s.max} 天</td>
                <td>${s.min} 天</td>
                <td>${s.avg} 天</td>
                <td>${s.median} 天</td>
            `;
            body.appendChild(tr);
        }
    });

    // Multi-Tier Average Streak Distribution Charts
    if (detailed.histograms) {
        Object.keys(detailed.histograms).forEach(label => {
            renderStreakChart(`${label}-streak-chart`, detailed.histograms[label]);
        });
    }

    // Message Count Ranking Chart
    if (detailed.all_msg_counts_sorted) {
        renderMsgRankingChart(detailed.all_msg_counts_sorted);
    }
}

let msgRankingChart = null;
function renderMsgRankingChart(counts) {
    const chartDom = document.getElementById('all-msg-ranking-chart');
    if (!msgRankingChart) {
        msgRankingChart = echarts.init(chartDom);
    }

    const labels = counts.map((_, i) => (i + 1).toString());
    
    const option = {
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'line' },
            formatter: function(params) {
                return `排名: ${params[0].name}<br/>消息数: ${params[0].value.toLocaleString()}`;
            }
        },
        dataZoom: [
            { type: 'inside', start: 0, end: 10 },
            { type: 'slider', start: 0, end: 10 }
        ],
        grid: {
            left: '3%', right: '4%', bottom: '15%', containLabel: true
        },
        xAxis: {
            type: 'category',
            data: labels,
            name: '用户排名',
            axisLabel: { show: labels.length < 50 } // Hide labels if too many
        },
        yAxis: {
            type: 'value',
            name: '消息数量'
        },
        series: [{
            data: counts,
            type: 'bar',
            itemStyle: { color: '#4e73df' },
            large: true // Optimize for many bars
        }]
    };
    msgRankingChart.setOption(option);
}

let streakCharts = {};
function renderStreakChart(domId, hist) {
    const chartDom = document.getElementById(domId);
    if (!chartDom) return;

    if (!streakCharts[domId]) {
        streakCharts[domId] = echarts.init(chartDom);
    }
    
    const option = {
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' }
        },
        grid: {
            left: '3%', right: '4%', bottom: '10%', containLabel: true
        },
        xAxis: [
            {
                type: 'category',
                data: hist.labels,
                axisTick: { alignWithLabel: true },
                axisLabel: { interval: 0, rotate: 30 }
            }
        ],
        yAxis: [
            {
                type: 'value',
                name: '用户数'
            }
        ],
        series: [
            {
                name: '用户数',
                type: 'bar',
                barWidth: '60%',
                data: hist.values,
                itemStyle: {
                    color: '#4e73df'
                }
            }
        ]
    };
    streakCharts[domId].setOption(option);
}

function startSync(isFull = false) {
    const btnInc = document.getElementById('btn-sync-chats');
    const btnFull = document.getElementById('btn-full-sync-chats');
    const wrap = document.getElementById('sync-progress-wrap');
    const status = document.getElementById('sync-status');
    const detail = document.getElementById('sync-detail');
    const fill = document.getElementById('sync-progress-fill');
    
    if (btnInc) btnInc.disabled = true;
    if (btnFull) btnFull.disabled = true;
    
    wrap.style.display = 'block';
    fill.style.width = '5%';
    status.textContent = isFull ? '初始化全量同步...' : '初始化增量同步...';
    
    const url = `/api/chats/sync?full=${isFull ? 'true' : 'false'}`;
    const eventSource = new EventSource(url);
    
    eventSource.addEventListener('progress', (e) => {
        const data = JSON.parse(e.data);
        status.textContent = data.msg;
        if (data.messages_synced !== undefined) {
            detail.textContent = `累计消息: ${data.messages_synced}`;
        }
        
        if (data.done) {
            fill.style.width = '100%';
            eventSource.close();
            if (btnInc) btnInc.disabled = false;
            if (btnFull) btnFull.disabled = false;
            showAlert(`${isFull ? '全量' : '增量'}同步完成：${data.conversations} 个会话，${data.messages} 条消息。`, 'success');
            loadDashboard();
        }
    });
    
    eventSource.addEventListener('error', (e) => {
        console.error('SSE Error:', e);
        eventSource.close();
        if (btnInc) btnInc.disabled = false;
        if (btnFull) btnFull.disabled = false;
        status.textContent = '同步出错';
        showAlert('同步过程中发生错误，请检查网络或日志。', 'error');
    });
}

document.getElementById('btn-sync-chats')?.addEventListener('click', () => startSync(false));
document.getElementById('btn-full-sync-chats')?.addEventListener('click', () => startSync(true));

async function checkOngoingSync() {
    try {
        const res = await fetch('/api/sync/status?task=chat_sync');
        const data = await res.json();
        
        if (data && !data.done) {
            // Restore UI state
            const wrap = document.getElementById('sync-progress-wrap');
            const status = document.getElementById('sync-status');
            const detail = document.getElementById('sync-detail');
            const fill = document.getElementById('sync-progress-fill');
            const btnInc = document.getElementById('btn-sync-chats');
            const btnFull = document.getElementById('btn-full-sync-chats');

            wrap.style.display = 'block';
            status.textContent = data.msg;
            if (data.percent !== undefined) fill.style.width = data.percent + '%';
            if (data.messages_synced !== undefined) detail.textContent = `累计消息: ${data.messages_synced}`;
            
            if (btnInc) btnInc.disabled = true;
            if (btnFull) btnFull.disabled = true;

            // Start polling until done
            const timer = setInterval(async () => {
                const r = await fetch('/api/sync/status?task=chat_sync');
                const d = await r.json();
                if (!d || d.done) {
                    clearInterval(timer);
                    if (btnInc) btnInc.disabled = false;
                    if (btnFull) btnFull.disabled = false;
                    if (d && !d.error) {
                        fill.style.width = '100%';
                        showAlert('同步已在后台完成', 'success');
                        loadDashboard();
                    } else if (d && d.error) {
                        showAlert(d.msg || '同步失败', 'error');
                    }
                } else {
                    status.textContent = d.msg;
                    if (d.percent !== undefined) fill.style.width = d.percent + '%';
                    if (d.messages_synced !== undefined) detail.textContent = `累计消息: ${d.messages_synced}`;
                }
            }, 2000);
        }
    } catch (err) {
        console.error('Failed to check sync status:', err);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadDashboard();
    checkOngoingSync();
});
