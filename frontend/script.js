// ===== CONFIG =====
const API_URL = 'https://was-washs.onrender.com/api';

// ===== STATE =====
let currentUser = null;
let selectedPackage = null;
let tasksCompleted = 0;
let referralLink = '';
let pendingDepositInterval = null;
let dashboardPollingInterval = null;
let completedTaskIds = JSON.parse(localStorage.getItem('completedTaskIds') || '[]');
const totalTasks = 3;

// ===== NAVIGATION =====
function showSection(sectionId) {
    const app = document.getElementById('app');
    if (app.classList.contains('hidden')) {
        showToast('Please login to access deposits and earnings.', 'info');
        return;
    }

    document.querySelectorAll('.section').forEach(s => s.classList.add('hidden'));
    document.getElementById(sectionId).classList.remove('hidden');
    
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    document.querySelector(`a[href="#${sectionId}"]`)?.classList.add('active');
    
    if (sectionId === 'tasks') loadTasks();
    if (sectionId === 'deposit') loadUserDeposits();
    if (sectionId === 'invest') { highlightSelectedInvestmentPackage(); loadUserInvestments(); }
    if (sectionId === 'withdraw') updateWithdrawDisplay();
}

function highlightSelectedInvestmentPackage() {
    if (!pendingInvestment) {
        document.querySelectorAll('.invest-packages .package-card').forEach(card => card.classList.remove('selected'));
        return;
    }
    document.querySelectorAll('.invest-packages .package-card').forEach(card => {
        const cardAmount = Number(card.dataset.amount || 0);
        const cardPackage = card.dataset.package || '';
        card.classList.toggle('selected', cardAmount === pendingInvestment.amount && cardPackage === pendingInvestment.packageName);
    });
}

document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        showSection(link.getAttribute('href').slice(1));
    });
});

// ===== AUTH =====
function switchAuth(type, event) {
    document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
    event?.target?.classList.add('active');
    
    document.getElementById('loginForm').classList.toggle('hidden', type !== 'login');
    document.getElementById('registerForm').classList.toggle('hidden', type !== 'register');
}

function validatePassword(password) {
    const lengthRule = password.length >= 8;
    const upperRule = /[A-Z]/.test(password);
    const lowerRule = /[a-z]/.test(password);
    const numberRule = /[0-9]/.test(password);
    const symbolRule = /[!@#$%^&*(),.?":{}|<>\[\]\\/;'`~_-]/.test(password);

    if (!lengthRule) return { valid: false, error: 'Password must be at least 8 characters.' };
    if (!upperRule) return { valid: false, error: 'Password must contain at least one uppercase letter.' };
    if (!lowerRule) return { valid: false, error: 'Password must contain at least one lowercase letter.' };
    if (!numberRule) return { valid: false, error: 'Password must contain at least one number.' };
    if (!symbolRule) return { valid: false, error: 'Password must contain at least one symbol.' };

    return { valid: true };
}

async function register() {
    const name = document.getElementById('regName').value.trim();
    const email = document.getElementById('regEmail').value.trim();
    const password = document.getElementById('regPassword').value;
    const confirmPassword = document.getElementById('regConfirmPassword').value;
    const phone = document.getElementById('regPhone').value.trim();
    const gender = document.getElementById('regGender').value.trim();
    const ageRaw = document.getElementById('regAge').value.trim();
    const referrerCode = localStorage.getItem('referrer') || '';
    const agreeTerms = document.getElementById('agreeTerms').checked;

    if (!name || !email || !password || !confirmPassword || !phone) {
        showToast('Please fill all fields', 'error');
        return;
    }

    if (!agreeTerms) {
        showToast('You must accept the Terms and Conditions to register', 'error');
        return;
    }

    if (password !== confirmPassword) {
        showToast('Passwords do not match', 'error');
        return;
    }

    const validation = validatePassword(password);
    if (!validation.valid) {
        showToast(validation.error, 'error');
        return;
    }

    const data = { name, email, password, phone, agree_terms: true };
    if (gender) {
        data.gender = gender;
    }
    if (ageRaw) {
        const age = parseInt(ageRaw, 10);
        if (Number.isNaN(age) || age < 1 || age > 120) {
            showToast('Please enter a valid age', 'error');
            return;
        }
        data.age = age;
    }
    if (referrerCode) {
        data.referrer_code = referrerCode;
    }

    try {
        const res = await fetch(`${API_URL}/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await res.json();
        
        if (res.ok) {
            localStorage.removeItem('referrer');
            showToast('Registration successful! Please login.', 'success');
            switchAuth('login');
        } else {
            showToast(result.error || 'Registration failed', 'error');
        }
    } catch (err) {
        showToast('Network error. Please try again.', 'error');
    }
}

async function login() {
    const data = {
        email: document.getElementById('loginEmail').value,
        password: document.getElementById('loginPassword').value
    };
    
    try {
        const res = await fetch(`${API_URL}/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await res.json();
        
        if (res.ok) {
            currentUser = result.user;
            localStorage.setItem('token', result.token);
            localStorage.setItem('user', JSON.stringify(result.user));
            completedTaskIds = [];
            localStorage.removeItem('completedTaskIds');
            enterApp();
            showToast(`Welcome back, ${result.user.name}!`, 'success');
        } else {
            showToast(result.error || 'Login failed', 'error');
        }
    } catch (err) {
        showToast('Network error. Please try again.', 'error');
    }
}

function toggleNavLinks(show) {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.style.display = show ? 'inline-flex' : 'none';
    });
}

function logout() {
    currentUser = null;
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    document.getElementById('auth').classList.remove('hidden');
    document.getElementById('app').classList.add('hidden');
    document.getElementById('userInfo').style.display = 'none';
    toggleNavLinks(false);
    stopDashboardPolling();
    showToast('Logged out successfully', 'info');
}

// ===== TERMS AND CONDITIONS =====
function showTermsModal() {
    document.getElementById('termsModal').classList.remove('hidden');
}

function closeTermsModal() {
    document.getElementById('termsModal').classList.add('hidden');
}

function enterApp() {
    document.getElementById('auth').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
    document.getElementById('userInfo').style.display = 'flex';
    toggleNavLinks(true);
    updateDashboard();
    loadUserDeposits();
    startDashboardPolling();
    showSection('dashboard');
}

// ===== INVESTMENTS =====
let pendingInvestment = null;
function investPackage(amount, packageName, image) {
    pendingInvestment = { amount, packageName, image };
    document.getElementById('invPackageName').textContent = packageName;
    document.getElementById('invAmount').textContent = `KSH ${Number(amount).toLocaleString()}`;
    const maturity = new Date(Date.now() + 60*24*60*60*1000); // 60 days
    document.getElementById('invMaturity').textContent = maturity.toDateString();
    document.getElementById('investModal').classList.remove('hidden');

    document.querySelectorAll('.invest-packages .package-card').forEach(card => {
        const cardAmount = Number(card.dataset.amount || 0);
        const cardPackage = card.dataset.package || '';
        card.classList.toggle('selected', cardAmount === amount && cardPackage === packageName);
    });
}

function closeInvestModal() {
    pendingInvestment = null;
    document.getElementById('investModal').classList.add('hidden');
    document.querySelectorAll('.invest-packages .package-card').forEach(card => card.classList.remove('selected'));
}

async function confirmInvestment() {
    if (!pendingInvestment) return;
    try {
        const res = await fetch(`${API_URL}/invest`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}` },
            body: JSON.stringify({ amount: pendingInvestment.amount, package: pendingInvestment.packageName, image: pendingInvestment.image })
        });
        const data = await res.json();
        if (!res.ok) { showToast(data.error || 'Investment failed', 'error'); return; }
        showToast('Investment created successfully', 'success');
        closeInvestModal();
        loadUserInvestments();
        updateDashboard();
    } catch (e) { showToast('Network error. Please try again.', 'error'); }
}

function highlightSelectedInvestmentPackage() {
    if (!pendingInvestment) {
        document.querySelectorAll('.invest-packages .package-card').forEach(card => card.classList.remove('selected'));
        return;
    }
    document.querySelectorAll('.invest-packages .package-card').forEach(card => {
        const cardAmount = Number(card.dataset.amount || 0);
        const cardPackage = card.dataset.package || '';
        card.classList.toggle('selected', cardAmount === pendingInvestment.amount && cardPackage === pendingInvestment.packageName);
    });
}

async function loadUserInvestments() {
    const el = document.getElementById('userInvestments');
    el.innerHTML = 'Loading…';
    try {
        const res = await fetch(`${API_URL}/user/investments`, { headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` } });
        const list = await res.json();
        if (!res.ok) { el.innerHTML = '<p class="message-list-empty">Unable to load investments</p>'; return; }
        if (!list.length) { el.innerHTML = '<p class="message-list-empty">No investments found.</p>'; return; }
        el.innerHTML = list.map(i => {
            const startDate = i.start_date ? new Date(i.start_date) : null;
            const maturityDate = i.maturity_date ? new Date(i.maturity_date) : null;
            const isMature = maturityDate && maturityDate <= new Date();
            const statusLabel = i.status === 'active' ? (isMature ? 'Matured' : 'Active') : i.status;
            const actionButton = i.status === 'active' && isMature
                ? `<button class="confirm-btn" onclick="withdrawInvestment(${i.id})">Withdraw</button>`
                : `<span class="investment-status ${escapeHtml(statusLabel.toLowerCase())}">${escapeHtml(statusLabel)}</span>`;
            return `
                <div class="investment-card">
                    <img src="${escapeHtml(i.image || 'images/money-bg.svg')}" alt="${escapeHtml(i.package_name || 'Investment')}" class="investment-thumb">
                    <div class="investment-info">
                        <strong>${escapeHtml(i.package_name || 'Custom Package')}</strong>
                        <div class="small-muted">KSH ${Number(i.amount).toLocaleString()}</div>
                        <div class="investment-dates">Started: ${startDate ? startDate.toLocaleDateString() : 'N/A'} • Matures: ${maturityDate ? maturityDate.toLocaleDateString() : 'N/A'}</div>
                    </div>
                    <div class="investment-actions">${actionButton}</div>
                </div>
            `;
        }).join('');
    } catch (e) { el.innerHTML = '<p class="message-list-empty">Network error while loading investments.</p>'; }
}

async function withdrawInvestment(invId) {
    try {
        const res = await fetch(`${API_URL}/user/investments/withdraw`, {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}` }, body: JSON.stringify({ investment_id: invId })
        });
        const data = await res.json();
        if (!res.ok) { showToast(data.error || 'Withdraw failed', 'error'); return; }
        showToast('Investment withdrawn. Funds credited to available balance.', 'success');
        loadUserInvestments();
        updateDashboard();
    } catch (e) { showToast('Network error. Please try again.', 'error'); }
}

// ===== DASHBOARD =====
async function updateDashboard() {
    if (!currentUser) return;
    
    try {
        const res = await fetch(`${API_URL}/user/dashboard`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await res.json();
        
        document.getElementById('totalDeposited').textContent = `KSH ${data.total_deposited.toLocaleString()}`;
        document.getElementById('dailyEarnings').textContent = `KSH ${data.daily_earnings.toLocaleString()}`;
        document.getElementById('totalEarned').textContent = `KSH ${data.total_earned.toLocaleString()}`;
        document.getElementById('availableBalance').textContent = `KSH ${data.available_balance.toLocaleString()}`;
        document.getElementById('userBalance').textContent = `KSH ${data.available_balance.toLocaleString()}`;

        document.getElementById('profileName').textContent = data.name || (currentUser && currentUser.name) || '-';
        document.getElementById('profileEmail').textContent = data.email || (currentUser && currentUser.email) || '-';
        document.getElementById('profilePhone').textContent = data.phone || (currentUser && currentUser.phone) || '-';
        document.getElementById('profileReferral').textContent = data.referral_code || (currentUser && currentUser.referral_code) || 'N/A';

        renderDashboardMessages(data.messages || []);

        if (currentUser) {
            currentUser.name = data.name || currentUser.name;
            currentUser.email = data.email || currentUser.email;
            currentUser.phone = data.phone || currentUser.phone;
            currentUser.referral_code = data.referral_code || currentUser.referral_code;
            currentUser.taskStatus = data.task_status || currentUser.taskStatus || {};
            localStorage.setItem('user', JSON.stringify(currentUser));
        }
        
        tasksCompleted = countCompletedTasks();
        updateTaskProgress();

        const progress = Math.round((tasksCompleted / totalTasks) * 100);
        if (data.pending_deposit_count > 0) {
            document.getElementById('depositStatus').textContent = 'Waiting for confirmation from admin...';
            document.getElementById('depositStatus').classList.remove('hidden');
            startPendingDepositPolling();
        } else {
            document.getElementById('depositStatus').classList.add('hidden');
            stopPendingDepositPolling();
        }
        document.getElementById('progressFill').style.width = `${progress}%`;
        document.getElementById('progressText').textContent = progress === 100 
            ? "Today's tasks are complete. You can claim earnings now." 
            : `Complete ${totalTasks - tasksCompleted} more tasks to unlock today's earnings`;
    } catch (err) {
        console.error('Dashboard update failed:', err);
    }
}

function startPendingDepositPolling() {
    if (pendingDepositInterval) return;
    pendingDepositInterval = setInterval(() => {
        updateDashboard();
        loadUserDeposits();
    }, 10000);
}

function stopPendingDepositPolling() {
    if (!pendingDepositInterval) return;
    clearInterval(pendingDepositInterval);
    pendingDepositInterval = null;
}

// ===== DEPOSIT =====
function selectPackage(amount) {
    selectedPackage = amount;
    document.getElementById('selectedAmount').textContent = `KSH ${amount.toLocaleString()}`;
    document.getElementById('sendAmount').textContent = `KSH ${amount.toLocaleString()}`;
    const phoneHint = document.getElementById('phoneHint');
    phoneHint.textContent = currentUser && currentUser.phone
        ? `A confirmation request will be sent to your registered phone: ${currentUser.phone}`
        : 'We will request confirmation on your registered mobile number once you submit.';
    document.getElementById('depositModal').classList.remove('hidden');
}

function closeDepositModal() {
    document.getElementById('depositModal').classList.add('hidden');
    selectedPackage = null;
}

async function confirmDeposit() {
    const mpesaCode = document.getElementById('mpesaCode').value.trim().toUpperCase();
    
    if (!mpesaCode || mpesaCode.length < 6) {
        showToast('Please enter a valid M-Pesa confirmation code', 'error');
        return;
    }
    
    try {
        const res = await fetch(`${API_URL}/deposit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('token')}`
            },
            body: JSON.stringify({
                amount: selectedPackage,
                mpesa_code: mpesaCode,
                mpesa_number: '0769261471'
            })
        });
        const result = await res.json();
        
        if (res.ok) {
            showToast('Deposit request submitted. Waiting for admin confirmation.', 'success');
            closeDepositModal();
            loadUserDeposits();
            updateDashboard();
        } else {
            showToast(result.error || 'Deposit failed', 'error');
        }
    } catch (err) {
        showToast('Network error. Please try again.', 'error');
    }
}

// ===== TASKS =====
const tasks = [
    { id: 1, key: 'ad', icon: '📺', title: 'Watch Advertisement', desc: 'Watch a 20-second EarnHub ad to earn KSH 100', reward: 'KSH 100' },
    { id: 2, key: 'survey', icon: '📝', title: 'Complete Survey', desc: 'Answer 5 quick questions to earn KSH 100', reward: 'KSH 100' },
    { id: 3, key: 'refer', icon: '👥', title: 'Refer a Friend', desc: 'Share your referral link to earn KSH 100', reward: 'KSH 100' }
];

function isTaskCompleted(task) {
    return !!(currentUser?.taskStatus?.[task.key] || completedTaskIds.includes(task.id));
}

function countCompletedTasks() {
    return tasks.reduce((count, task) => count + (isTaskCompleted(task) ? 1 : 0), 0);
}

function loadTasks() {
    const container = document.getElementById('tasksContainer');
    container.innerHTML = '';
    tasksCompleted = 0;
    
    tasks.forEach((task) => {
        const completed = isTaskCompleted(task);
            const card = document.createElement('div');
            card.className = 'task-card';
            const isLoggedIn = !!currentUser;
            const adLabel = isLoggedIn ? 'Watch Ad' : 'Start';
            const surveyLabel = isLoggedIn ? 'Complete Survey' : 'Start';
            const referLabel = isLoggedIn ? 'Refer a Friend' : 'Start';
            const defaultLabel = 'Start';
            const statusBadge = completed ? '<span class="task-status-badge">Completed</span>' : '';
            card.innerHTML = `
                <div class="task-icon">${task.icon}</div>
                <div class="task-content">
                    <div class="task-title">${task.title}</div>
                    <div class="task-desc">${task.desc}</div>
                    <div class="task-reward">${task.reward}</div>
                    ${statusBadge}
                </div>
                <button class="task-btn ${completed ? 'completed' : ''}" id="task-${task.id}">
                    ${completed ? '✓ Completed' : task.id === 1 ? adLabel : task.id === 2 ? surveyLabel : task.id === 3 ? referLabel : defaultLabel}
                </button>
            `;
            container.appendChild(card);
            const btn = card.querySelector('button');
            if (task.id === 1) {
                btn.addEventListener('click', showAdPage);
            } else if (task.id === 2) {
                btn.addEventListener('click', showSurvey);
            } else if (task.id === 3) {
                btn.addEventListener('click', showReferralPage);
            } else {
                btn.addEventListener('click', () => completeTask(task.id));
            }
            if (completed) tasksCompleted++;
    });
    
    updateTaskProgress();
}

function completeTask(taskId) {
    const btn = document.getElementById(`task-${taskId}`);
    if (btn.classList.contains('completed')) return;
    
    // Simulate task completion
    btn.textContent = 'Processing...';
    btn.disabled = true;
    
    setTimeout(() => {
        btn.textContent = '✓ Completed';
        btn.classList.add('completed');
        btn.disabled = false;
        if (!completedTaskIds.includes(taskId)) {
            completedTaskIds.push(taskId);
            localStorage.setItem('completedTaskIds', JSON.stringify(completedTaskIds));
        }
        tasksCompleted++;
        updateTaskProgress();
        showToast('Task completed!', 'success');
    }, 1500);
}

function updateTaskProgress() {
    document.getElementById('tasksCompleted').textContent = tasksCompleted;
    document.getElementById('tasksTotal').textContent = totalTasks;
    
    const claimBtn = document.getElementById('claimBtn');
    if (tasksCompleted >= totalTasks) {
        claimBtn.disabled = false;
        claimBtn.textContent = 'Claim Today\'s Earnings!';
    } else {
        claimBtn.disabled = true;
        claimBtn.textContent = `Complete ${totalTasks - tasksCompleted} more tasks`;
    }
}

async function claimEarnings() {
    try {
        const res = await fetch(`${API_URL}/claim-earnings`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('token')}`
            }
        });
        const result = await res.json();
        
        if (res.ok) {
            showToast(`You earned KSH ${result.amount_earned}!`, 'success');
            updateDashboard();
            document.getElementById('claimBtn').disabled = true;
            document.getElementById('claimBtn').textContent = 'Earnings Claimed for Today';
        } else {
            showToast(result.error || 'Could not claim earnings', 'error');
        }
    } catch (err) {
        showToast('Network error. Please try again.', 'error');
    }
}

// ===== WITHDRAW =====
function updateWithdrawDisplay() {
    if (!currentUser) return;
    // Refresh from server
    updateDashboard();
}

function renderDashboardMessages(messages) {
    const list = document.getElementById('messageList');
    if (!messages || messages.length === 0) {
        list.innerHTML = '<p class="message-list-empty">No messages yet.</p>';
        return;
    }

    list.innerHTML = messages.map(msg => `
        <div class="message-card-item">
            <div><strong>${msg.subject}</strong><span class="status status-${msg.status}">${msg.status}</span></div>
            <p>${msg.body}</p>
            <div class="response-box">${msg.admin_response ? `<strong>Admin response:</strong> ${msg.admin_response}` : '<em>No response yet</em>'}</div>
            <small>${new Date(msg.created_at).toLocaleString()}</small>
        </div>
    `).join('');
}

async function sendMessage() {
    const subject = document.getElementById('messageSubject').value.trim();
    const body = document.getElementById('messageBody').value.trim();

    if (!subject || !body) {
        showToast('Please enter subject and message body', 'error');
        return;
    }

    try {
        const res = await fetch(`${API_URL}/messages`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('token')}`
            },
            body: JSON.stringify({ subject, body })
        });
        const result = await res.json();
        if (res.ok) {
            document.getElementById('messageSubject').value = '';
            document.getElementById('messageBody').value = '';
            showToast('Message sent to admin', 'success');
            updateDashboard();
        } else {
            showToast(result.error || 'Could not send message', 'error');
        }
    } catch (err) {
        showToast('Network error. Please try again.', 'error');
    }
}

async function loadUserDeposits() {
    if (!currentUser) return;

    try {
        const res = await fetch(`${API_URL}/user/pending-requests`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await res.json();
        const list = document.getElementById('depositRequests');
        const statusCard = document.getElementById('depositStatus');
        
        if (!res.ok) {
            list.innerHTML = '<p>Could not load deposit requests.</p>';
            return;
        }

        if (!data.deposits || data.deposits.length === 0) {
            list.innerHTML = '<p>No deposit requests yet. Choose a package to start.</p>';
            statusCard.classList.add('hidden');
            return;
        }

        list.innerHTML = data.deposits.map(d => `
            <div class="deposit-request-card ${d.status}">
                <strong>Amount:</strong> KSH ${Number(d.amount).toLocaleString()}<br>
                <strong>Status:</strong> ${d.status === 'pending' ? 'Waiting for confirmation' : d.status === 'approved' ? 'Approved' : d.status}<br>
                <strong>M-Pesa code:</strong> ${d.mpesa_code}<br>
                <strong>Requested:</strong> ${new Date(d.created_at).toLocaleString()}
            </div>
        `).join('');

        if (data.pending_deposit_count > 0) {
            statusCard.textContent = 'Waiting for confirmation from admin...';
            statusCard.classList.remove('hidden');
            startPendingDepositPolling();
        } else {
            statusCard.classList.add('hidden');
            stopPendingDepositPolling();
        }

        if (data.messages && data.messages.length > 0) {
            renderDashboardMessages(data.messages);
        }
    } catch (err) {
        console.error('Could not load deposits', err);
    }
}

function getReferralLink() {
    if (!currentUser || !currentUser.referral_code) return '';
    const origin = window.location.origin || `${window.location.protocol}//${window.location.host}`;
    const basePath = window.location.pathname.replace(/\/index\.html$/i, '');
    return `${origin}${basePath}?ref=${encodeURIComponent(currentUser.referral_code)}`;
}

function showAdPage() {
    if (!currentUser) {
        showToast('Please login to watch the ad.', 'info');
        document.getElementById('auth').classList.remove('hidden');
        document.getElementById('app').classList.add('hidden');
        return;
    }
    window.location.href = 'ad.html';
}

function showReferralPage() {
    if (!currentUser || !currentUser.referral_code) {
        showToast('Your referral link is not available yet.', 'error');
        return;
    }

    referralLink = getReferralLink();
    const input = document.getElementById('referralPageLinkInput');
    input.value = referralLink;
    document.getElementById('referralStatus').textContent = 'Share this link via WhatsApp, and once your friend deposits, your reward will be applied automatically after admin approval.';
    showSection('refer');
    markReferralTaskCompleted();
}

// Rating task removed — function intentionally deleted.

function markReferralTaskCompleted() {
    const btn = document.getElementById('task-3');
    if (btn && !btn.classList.contains('completed')) {
        btn.textContent = '✓ Completed';
        btn.classList.add('completed');
        if (!completedTaskIds.includes(3)) {
            completedTaskIds.push(3);
            localStorage.setItem('completedTaskIds', JSON.stringify(completedTaskIds));
        }
        tasksCompleted++;
        updateTaskProgress();
    }
}

function copyReferralPageLink() {
    if (!referralLink) {
        referralLink = getReferralLink();
    }
    const input = document.getElementById('referralPageLinkInput');
    input.value = referralLink;

    if (!navigator.clipboard) {
        input.select();
        document.execCommand('copy');
        showToast('Referral link copied! Send it to a friend on WhatsApp.', 'success');
        return;
    }

    navigator.clipboard.writeText(referralLink)
        .then(() => showToast('Referral link copied! Send it to a friend on WhatsApp.', 'success'))
        .catch(() => showToast('Could not copy link, please copy manually.', 'error'));
}

function shareReferralWhatsApp() {
    if (!referralLink) {
        referralLink = getReferralLink();
    }
    const message = encodeURIComponent(`Join EarnHub and grow your savings! Use my referral link: ${referralLink}`);
    const whatsappUrl = `https://wa.me/?text=${message}`;
    window.open(whatsappUrl, '_blank');
}

// ===== SURVEY =====
function showSurvey() {
    if (!currentUser) {
        showToast('Please login to start the survey.', 'info');
        document.getElementById('auth').classList.remove('hidden');
        document.getElementById('app').classList.add('hidden');
        return;
    }
    window.location.href = 'survey.html';
}

function closeSurveyModal() {
    if (document.getElementById('surveyModal')) {
        document.getElementById('surveyModal').classList.add('hidden');
    }
}

async function submitSurvey() {
    const answers = {
        q1: document.getElementById('q1').value,
        q2: document.getElementById('q2').value,
        q3: document.getElementById('q3').value,
        q4: document.getElementById('q4').value,
        q5: document.getElementById('q5').value
    };

    if (!answers.q1 || !answers.q2 || !answers.q3 || !answers.q4) {
        showToast('Please answer all required questions.', 'error');
        return;
    }

    try {
        const res = await fetch(`${API_URL}/survey/submit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('token')}`
            },
            body: JSON.stringify({ answers })
        });
        const result = await res.json();
        if (res.ok) {
            markSurveyCompleted(result.reward || 0);
            showToast(`Survey submitted! You earned KSH ${result.reward}.`, 'success');
            updateDashboard();
            // hide survey and show simple thank-you section
            const surveySection = document.getElementById('surveySection');
            const thankYouSection = document.getElementById('thankYouSection');
            if (surveySection && thankYouSection) {
                surveySection.classList.add('hidden');
                thankYouSection.classList.remove('hidden');
            }
        } else {
            showToast(result.error || 'Could not submit survey', 'error');
        }
    } catch (err) {
        console.error('Survey submission failed', err);
        showToast('Network error. Please try again.', 'error');
    }
}

function markSurveyCompleted(rewardAmount) {
    const btn = document.getElementById('task-2');
    if (btn && !btn.classList.contains('completed')) {
        btn.textContent = '✓ Completed';
        btn.classList.add('completed');
        if (!completedTaskIds.includes(2)) {
            completedTaskIds.push(2);
            localStorage.setItem('completedTaskIds', JSON.stringify(completedTaskIds));
        }
        tasksCompleted++;
        updateTaskProgress();
    }
}

async function withdraw() {
    const amount = parseFloat(document.getElementById('withdrawAmount').value);
    const phone = document.getElementById('withdrawPhone').value;
    
    if (!amount || amount < 100) {
        showToast('Minimum withdrawal is KSH 100', 'error');
        return;
    }
    
    if (!phone || phone.length < 10) {
        showToast('Please enter a valid M-Pesa number', 'error');
        return;
    }
    
    try {
        const res = await fetch(`${API_URL}/withdraw`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('token')}`
            },
            body: JSON.stringify({ amount, phone })
        });
        const result = await res.json();
        
        if (res.ok) {
            showToast('Withdrawal request submitted!', 'success');
            updateDashboard();
            document.getElementById('withdrawAmount').value = '';
            document.getElementById('withdrawPhone').value = '';
        } else {
            showToast(result.error || 'Withdrawal failed', 'error');
        }
    } catch (err) {
        showToast('Network error. Please try again.', 'error');
    }
}

// ===== UTILITIES =====
function startDashboardPolling() {
    if (dashboardPollingInterval) return;
    dashboardPollingInterval = setInterval(() => {
        updateDashboard();
        loadUserDeposits();
    }, 10000);
}

function stopDashboardPolling() {
    if (!dashboardPollingInterval) return;
    clearInterval(dashboardPollingInterval);
    dashboardPollingInterval = null;
}

function initializeReferralQuery() {
    const params = new URLSearchParams(window.location.search);
    const referrer = params.get('ref');
    if (referrer) {
        localStorage.setItem('referrer', referrer);
        history.replaceState(null, '', window.location.pathname);
        showToast('Referral link detected. Complete registration to credit the referrer.', 'success');
    }
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type}`;
    
    setTimeout(() => {
        toast.classList.add('hidden');
    }, 4000);
}

// ===== INIT =====
window.addEventListener('DOMContentLoaded', () => {
    toggleNavLinks(false);
    initializeReferralQuery();

    const savedUser = localStorage.getItem('user');
    const token = localStorage.getItem('token');
    
    if (savedUser && token) {
        currentUser = JSON.parse(savedUser);
        enterApp();
    }

    const savedTaskIds = localStorage.getItem('completedTaskIds');
    if (savedTaskIds) {
        completedTaskIds = JSON.parse(savedTaskIds);
    }
});