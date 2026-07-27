const API_URL = '/api';

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

function getUser() {
    try {
        return JSON.parse(localStorage.getItem('user'));
    } catch {
        return null;
    }
}

function markSurveyCompleted(rewardAmount) {
    const savedTaskIds = JSON.parse(localStorage.getItem('completedTaskIds') || '[]');
    if (!savedTaskIds.includes(2)) {
        savedTaskIds.push(2);
        localStorage.setItem('completedTaskIds', JSON.stringify(savedTaskIds));
    }
    showToast(`Survey complete! Earned KSH ${rewardAmount}.`, 'success');
}

async function submitSurvey() {
    const token = getToken();
    if (!token) {
        showToast('Please login first.', 'error');
        window.location.href = 'index.html';
        return;
    }

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
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ answers })
        });
        const result = await res.json();

        if (res.ok) {
            markSurveyCompleted(result.reward || 0);
            document.getElementById('surveySection').classList.add('hidden');
            document.getElementById('thankYouSection').classList.remove('hidden');
            showToast(`Survey submitted! You earned KSH ${result.reward}.`, 'success');
        } else {
            const errorMessage = result.error || result.msg || 'Could not submit survey';
            showToast(errorMessage, 'error');
            if (res.status === 401 || res.status === 403) {
                setTimeout(() => { window.location.href = 'index.html'; }, 2000);
            }
        }
    } catch (err) {
        console.error('Survey submission failed', err);
        showToast('Network error. Please try again.', 'error');
    }
}

// Rating flow removed — rating UI and submission disabled.

window.addEventListener('DOMContentLoaded', () => {
    const token = getToken();
    if (!token) {
        document.getElementById('surveySection').classList.add('hidden');
        document.getElementById('notLoggedInMessage').classList.remove('hidden');
        showToast('Please login to continue.', 'info');
        setTimeout(() => {
            window.location.href = 'index.html';
        }, 2500);
        return;
    }
    // No rating flow — simply allow the survey to be completed on this page.
});
