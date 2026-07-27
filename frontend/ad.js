const API_URL = 'https://was-washs.onrender.com/api';
let countdownInterval = null;
let countdownValue = 20;

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.className = `toast ${type}`;
    toast.classList.remove('hidden');
    setTimeout(() => toast.classList.add('hidden'), 4000);
}

function getToken() {
    return localStorage.getItem('token');
}

function markAdCompleted(rewardAmount) {
    const savedTaskIds = JSON.parse(localStorage.getItem('completedTaskIds') || '[]');
    if (!savedTaskIds.includes(1)) {
        savedTaskIds.push(1);
        localStorage.setItem('completedTaskIds', JSON.stringify(savedTaskIds));
    }
    showToast(`Ad complete! Earned KSH ${rewardAmount}.`, 'success');
}

function startAd() {
    const token = getToken();
    if (!token) {
        showToast('Please login to watch the ad.', 'error');
        setTimeout(() => window.location.href = 'index.html', 1500);
        return;
    }

    // Reset countdown each time user starts the ad
    countdownValue = 20;
    document.getElementById('startAdButton').disabled = true;
    document.getElementById('countdownText').classList.remove('hidden');
    document.getElementById('countdownValue').textContent = countdownValue;

    countdownInterval = setInterval(() => {
        countdownValue -= 1;
        document.getElementById('countdownValue').textContent = countdownValue;
        if (countdownValue <= 0) {
            clearInterval(countdownInterval);
            completeAd();
        }
    }, 1000);
}

async function completeAd() {
    const token = getToken();
    if (!token) {
        showError('Login required to claim the reward.');
        return;
    }

    try {
        const res = await fetch(`${API_URL}/ad/complete`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            }
        });

        // Try to parse JSON, but fall back to text for clearer errors
        let result = null;
        try {
            result = await res.json();
        } catch (err) {
            const text = await res.text();
            result = { error: text };
        }

        if (res.ok) {
            markAdCompleted(result.reward || 0);
            document.getElementById('adIntro').classList.add('hidden');
            document.getElementById('adCompleteSection').classList.remove('hidden');
        } else {
            const msg = result && (result.error || result.message || result.msg) ? (result.error || result.message || result.msg) : `Server responded ${res.status}`;
            // If unauthorized, redirect to login after notifying
            if (res.status === 401 || res.status === 403) {
                showError(msg + ' Redirecting to login...');
                setTimeout(() => window.location.href = 'index.html', 1600);
                return;
            }
            showError(msg || 'Could not complete the ad.');
        }
    } catch (err) {
        console.error(err);
        showError('Network error. Please try again.');
    }
}

function showError(message) {
    document.getElementById('adIntro').classList.add('hidden');
    document.getElementById('adErrorSection').classList.remove('hidden');
    document.getElementById('adErrorMessage').textContent = message;
    showToast(message, 'error');
}

window.addEventListener('DOMContentLoaded', () => {
    const token = getToken();
    if (!token) {
        document.getElementById('startAdButton').disabled = true;
        showToast('Please login first to claim your reward.', 'info');
    }
});
