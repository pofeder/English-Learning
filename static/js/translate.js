const TranslationExercise = (() => {
    function render(container, exercises) {
        if (!exercises || exercises.length === 0) {
            container.innerHTML = '<p style="color:var(--ink-muted);text-align:center;padding:20px;">暂无翻译练习</p>';
            return;
        }
        container.innerHTML = exercises.map((ex) => {
            const submitted = ex.user_translation && ex.feedback;
            return `
                <div class="exercise-item" data-exercise-id="${ex.id}">
                    <div class="exercise-number">句子 ${ex.sentence_index + 1} / ${exercises.length}</div>
                    <div class="exercise-en">${esc(ex.english_sentence)}</div>
                    ${submitted ? renderFeedback(ex) : renderInput(ex.id)}
                </div>`;
        }).join("");
    }

    function renderInput(exId) {
        return `
            <textarea class="exercise-input" placeholder="在此输入你的中文翻译..."></textarea>
            <div class="exercise-actions">
                <button class="submit-btn" onclick="TranslationExercise.submit(this, ${exId})">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                    提交批改
                </button>
            </div>`;
    }

    function renderFeedback(ex) {
        const sc = ex.score >= 8 ? "score-high" : ex.score >= 5 ? "score-mid" : "score-low";
        let issues = [];
        try { issues = typeof ex.key_issues === "string" ? JSON.parse(ex.key_issues) : (ex.key_issues || []); } catch(e) {}

        return `
            <div class="feedback-block">
                <div class="feedback-score-row">
                    <span class="score-badge ${sc}">${ex.score}</span>
                    <span class="score-label">/10 分 · ${ex.score >= 8 ? '优秀' : ex.score >= 5 ? '良好' : '需加强'}</span>
                </div>
                <div class="feedback-section">
                    <div class="feedback-section-label">你的翻译</div>
                    <div class="feedback-user-text">${esc(ex.user_translation)}</div>
                </div>
                <div class="feedback-section">
                    <div class="feedback-section-label">AI 批改反馈</div>
                    <div class="feedback-ai-text">${esc(ex.feedback)}</div>
                </div>
                ${issues.length ? `
                    <div class="feedback-section">
                        <div class="feedback-section-label">主要问题</div>
                        <ul class="feedback-issues">${issues.map(i => `<li>${esc(i)}</li>`).join("")}</ul>
                    </div>
                ` : ""}
                <div class="feedback-section">
                    <div class="feedback-section-label">参考译文</div>
                    <div class="feedback-reference-text">${esc(ex.reference_translation)}</div>
                </div>
                <button class="retry-btn" onclick="TranslationExercise.retry(this, ${ex.id})">重新翻译</button>
            </div>`;
    }

    async function submit(btn, exId) {
        const item = btn.closest(".exercise-item");
        const textarea = item.querySelector(".exercise-input");
        const text = textarea.value.trim();

        if (!text) {
            textarea.style.borderColor = "var(--red)";
            textarea.focus();
            setTimeout(() => { textarea.style.borderColor = ""; }, 1500);
            return;
        }

        const origHTML = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-sm"></span> 批改中...';
        textarea.disabled = true;

        try {
            const resp = await fetch("/api/translate/submit", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ exercise_id: exId, user_translation: text }),
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || "请求失败");
            }
            const data = await resp.json();

            item.querySelectorAll(".exercise-input, .exercise-actions").forEach(el => el.remove());
            const div = document.createElement("div");
            div.innerHTML = renderFeedback({
                user_translation: text,
                feedback: data.feedback,
                score: data.score,
                key_issues: data.key_issues || [],
                reference_translation: data.reference_translation,
            });
            item.appendChild(div.firstElementChild);
        } catch (e) {
            Toast.show("批改失败: " + e.message, "error");
            btn.disabled = false;
            btn.innerHTML = origHTML;
            textarea.disabled = false;
        }
    }

    function retry(btn, exId) {
        const item = btn.closest(".exercise-item");
        item.querySelectorAll(".feedback-block, .retry-btn").forEach(el => el.remove());
        const div = document.createElement("div");
        div.innerHTML = renderInput(exId);
        while (div.firstElementChild) item.appendChild(div.firstElementChild);
    }

    function esc(s) {
        if (!s) return "";
        const d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    return { render, submit, retry };
})();
