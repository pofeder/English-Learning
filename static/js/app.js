/* english-daily v5 — warm paper design, stamp checkin, staggered paragraphs */
(() => {
    "use strict";
    let currentArticleId = null;
    let glossaryMap = new Map();
    let wordDefinitionMap = new Map();
    let ttsPlaying = false;

    const $ = (id) => document.getElementById(id);

    // ═══ Toast ════════════════════════════
    window.Toast = {
        show(msg, type = "") {
            const c = $("toast-container");
            if (!c) return;
            const t = document.createElement("div");
            t.className = "toast " + type;
            t.textContent = msg;
            c.appendChild(t);
            setTimeout(() => { if (t.parentNode) t.remove(); }, 3200);
        }
    };

    // ═══ Init ════════════════════════════
    document.addEventListener("DOMContentLoaded", async () => {
        setTodayDate();
        setupReadingProgress();
        setupKeyboardShortcuts();
        setupTooltipCallback();
        setupDarkMode();
        const dashboardPromise = loadDashboardData();
        await loadArchive();
        await loadTodayArticle();
        setupArchiveChange();
        setupStatsModal();
        await loadCheckinStatus();
        await dashboardPromise;
    });

    function setTodayDate() {
        const el = $("date-badge");
        if (!el) return;
        const now = new Date();
        el.textContent = now.getFullYear() + "年" + (now.getMonth() + 1) + "月" + now.getDate() + "日";
    }

    // ═══ Daily dashboard ═══════════════
    async function loadDashboardData() {
        const [stats, flashcards, mistakes] = await Promise.all([
            fetch("/api/stats").then(r => r.ok ? r.json() : null).catch(() => null),
            fetch("/api/flashcard/due?limit=1").then(r => r.ok ? r.json() : null).catch(() => null),
            fetch("/api/mistakes/stats").then(r => r.ok ? r.json() : null).catch(() => null),
        ]);

        if (stats) {
            setText("dashboard-word-count", stats.unique_words ?? "—");
            setText("dashboard-exercise-count", stats.total_exercises ?? "—");
        }

        if (flashcards) {
            const due = Number(flashcards.due_count || 0);
            setText("dashboard-flashcard-meta", due > 0 ? `今天有 ${due} 个单词待复习` : "今日无需复习，继续保持");
            setDashboardState("dashboard-flashcard-state", due > 0 ? "开始复习" : "已清空", due > 0 ? "ready" : "clear");
        }

        if (mistakes) {
            const pending = Number(mistakes.unreviewed || 0);
            setText("dashboard-mistake-meta", pending > 0 ? `还有 ${pending} 道题等待复盘` : "暂无待复盘错题");
            setDashboardState("dashboard-mistake-state", pending > 0 ? "待复盘" : "已清空", pending > 0 ? "ready" : "clear");
        }
    }

    function setDashboardState(id, text, state) {
        const el = $(id);
        if (!el) return;
        el.textContent = text;
        el.classList.remove("is-ready", "is-clear");
        if (state === "ready") el.classList.add("is-ready");
        if (state === "clear") el.classList.add("is-clear");
    }

    // ═══ Reading progress ═══════════════
    function setupReadingProgress() {
        const bar = $("reading-progress");
        if (!bar) return;
        window.addEventListener("scroll", () => {
            const h = document.documentElement.scrollHeight - window.innerHeight;
            bar.style.width = h > 0 ? Math.min(100, (window.scrollY / h) * 100) + "%" : "0%";
        }, { passive: true });
    }

    // ═══ Keyboard shortcuts ═════════════
    function setupKeyboardShortcuts() {
        document.addEventListener("keydown", (e) => {
            if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.isContentEditable) return;
            if (!document.querySelector(".sentence-block")) return;

            switch (e.key.toLowerCase()) {
                case "t":
                    const blocks = document.querySelectorAll(".sentence-block");
                    const anyVisible = Array.from(blocks).some(b => b.classList.contains("translation-visible"));
                    blocks.forEach(b => {
                        const zh = b.querySelector(".sentence-zh");
                        if (anyVisible) { b.classList.remove("translation-visible"); if (zh) zh.style.display = "none"; }
                        else { b.classList.add("translation-visible"); if (zh) zh.style.display = "block"; }
                    });
                    break;
                case "arrowleft": {
                    e.preventDefault();
                    const sel = $("archive-select");
                    if (sel && sel.selectedIndex > 0) { sel.selectedIndex--; sel.dispatchEvent(new Event("change")); }
                    break;
                }
                case "arrowright": {
                    e.preventDefault();
                    const s = $("archive-select");
                    if (s && s.selectedIndex < s.options.length - 1) { s.selectedIndex++; s.dispatchEvent(new Event("change")); }
                    break;
                }
            }
        });
    }

    // ═══ Dark mode ═════════════════════
    function setupDarkMode() {
        const btn = $("theme-toggle");
        if (!btn) return;
        if (localStorage.getItem("darkMode") === "1") document.body.classList.add("dark");
        updateThemeIcon();
        btn.addEventListener("click", () => {
            document.body.classList.toggle("dark");
            localStorage.setItem("darkMode", document.body.classList.contains("dark") ? "1" : "0");
            updateThemeIcon();
        });
    }
    function updateThemeIcon() {
        const btn = $("theme-toggle");
        if (!btn) return;
        btn.innerHTML = document.body.classList.contains("dark") ? "☀" : "🌙";
    }

    // ═══ TTS ════════════════════════════
    function setupTTS() {
        const btn = $("tts-btn");
        if (!btn) return;
        btn.addEventListener("click", toggleTTS);
    }

    function toggleTTS() {
        const btn = $("tts-btn");
        if (!btn) return;
        if (ttsPlaying) {
            window.speechSynthesis.cancel();
            ttsPlaying = false;
            btn.classList.remove("playing");
            btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg> 朗读';
            return;
        }
        const body = $("article-body");
        if (!body) return;
        const text = body.textContent.replace(/\s+/g, " ").trim();
        if (!text) return;
        const utter = new SpeechSynthesisUtterance(text);
        utter.lang = "en-US";
        utter.rate = 0.85;
        utter.onstart = () => {
            ttsPlaying = true;
            btn.classList.add("playing");
            btn.innerHTML = '<span class="spinner-sm"></span> 播放中';
        };
        utter.onend = utter.onerror = () => {
            ttsPlaying = false;
            btn.classList.remove("playing");
            btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg> 朗读';
        };
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(utter);
    }

    // ═══ Check-in — stamp animation ═════
    async function loadCheckinStatus() {
        try {
            const resp = await fetch("/api/checkin/status");
            const data = await resp.json();
            const row = $("checkin-row");
            const btn = $("stamp-btn");
            const streakEl = $("streak-count");
            if (!row) return;
            row.style.display = "flex";
            if (streakEl) streakEl.textContent = data.streak;
            setText("dashboard-streak-count", data.streak ?? "—");

            if (data.checked_in_today) {
                if (btn) { btn.classList.add("checked"); btn.disabled = true; }
            } else {
                if (btn) btn.addEventListener("click", async () => {
                    btn.disabled = true;
                    try {
                        const r = await fetch("/api/checkin", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ article_id: currentArticleId }),
                        });
                        const d = await r.json();
                        btn.classList.add("checked");
                        if (streakEl) streakEl.textContent = d.streak;
                        setText("dashboard-streak-count", d.streak ?? "—");
                        Toast.show("打卡成功！连续 " + d.streak + " 天", "success");
                    } catch (e) {
                        btn.disabled = false;
                        Toast.show("打卡失败", "error");
                    }
                });
            }

            const toggle = $("heatmap-toggle");
            if (toggle) toggle.addEventListener("click", () => {
                const c = $("heatmap-container");
                if (c) c.style.display = c.style.display === "none" ? "block" : "none";
            });
            if (data.checkin_dates && data.checkin_dates.length > 0) buildHeatmap(data.checkin_dates);
        } catch (e) { /* ignore */ }
    }

    function buildHeatmap(dates) {
        const container = $("heatmap-container");
        if (!container) return;
        const dateSet = new Set(dates);
        const now = new Date();
        const weeks = [];
        for (let d = new Date(now); d > new Date(now.getTime() - 365 * 86400000); d.setDate(d.getDate() - 1)) {
            const ds = d.toISOString().slice(0, 10);
            if (!weeks[0] || weeks[0].length >= 7) weeks.unshift([]);
            weeks[0].push({ date: ds, checked: dateSet.has(ds) });
        }
        const recent = weeks.slice(-20);
        container.innerHTML = `
            <div class="heatmap-grid">${recent.map(w =>
                '<div class="heatmap-week">' + w.map(c => {
                    const level = c.checked ? Math.min(5, 3) : 0;
                    return '<div class="heatmap-cell' + (level > 0 ? ' l' + level : '') + '" title="' + c.date + (c.checked ? ' ✓' : '') + '"></div>';
                }).join("") + '</div>'
            ).join("")}</div>
            <div class="heatmap-legend"><span>更少</span><span class="heatmap-cell"></span><span class="heatmap-cell l2"></span><span class="heatmap-cell l4"></span><span>更多</span></div>`;
    }

    // ═══ Tooltip callback ═══════════════
    function setupTooltipCallback() {
        if (typeof Tooltip === "undefined") return;
        Tooltip.setMarkCallback(async (word) => {
            try {
                await fetch("/api/word/mark-unfamiliar", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ word, article_id: currentArticleId }),
                });
                Toast.show('"' + word + '" 已加入单词本', "success");
            } catch (e) { Toast.show("标记失败", "error"); }
        });
    }

    // ═══ Load article ═══════════════════
    async function loadTodayArticle() {
        showLoading(true);
        hideError();
        try {
            const resp = await fetch("/api/article/today");
            if (!resp.ok) {
                if (resp.status === 404) showNoArticle();
                else showError("加载文章失败，请刷新页面重试。");
                return;
            }
            renderArticle(await resp.json());
        } catch (e) {
            showError("网络连接失败: " + e.message);
        } finally { showLoading(false); }
    }

    function renderArticle(article) {
        currentArticleId = article.id;
        buildGlossaryMap(article.glossary, article.word_definitions);

        const section = $("article-section");
        if (!section) return;
        section.style.display = "block";

        hideError();

        setText("article-title", article.title);
        setText("article-title-zh", article.chinese_title || "");
        setText("dashboard-article-title", article.title || "阅读文章并标记生词");
        setDashboardState("dashboard-reading-state", "进行中", "ready");

        const srcEl = $("article-source");
        if (srcEl) {
            srcEl.innerHTML = (article.source || "") +
                (article.difficulty_description ? ' · <span>' + esc(article.difficulty_description) + '</span>' : "");
        }

        const metaEl = $("article-meta-extra");
        if (metaEl && article.difficulty_score) {
            const ds = article.difficulty_score;
            const label = ds >= 8.5 ? "较难" : ds >= 7.5 ? "中等偏难" : ds >= 6.5 ? "中等" : "中等偏易";
            const color = ds >= 8.5 ? "var(--red)" : ds >= 7.5 ? "var(--amber)" : "var(--green)";
            metaEl.innerHTML = '<span class="meta-tag" style="color:' + color + ';font-weight:600;">' + (article.cefr_level || "") + ' · ' + ds + '分 · ' + label + '</span>';
        }

        setText("article-word-count", (article.word_count || 0) + " words");
        setText("article-date", fmtDate(article.created_at));

        // Article body
        const body = $("article-body");
        if (!body) return;
        const paras = article.content.split(/\n\n+/).filter(p => p.trim());
        const zhParas = (article.chinese_content || "").split(/\n\n+/).filter(p => p.trim());
        body.innerHTML = paras.map((para, pi) => buildParagraph(para, zhParas[pi] || "")).join("");

        // Glossary strip
        setupGlossary(article.glossary);

        // Word clicks
        body.querySelectorAll(".word-clickable").forEach(span => {
            span.addEventListener("click", async (e) => {
                e.stopPropagation();
                await showWordDefinition(span.dataset.word, span);
            });
        });

        // Sentence clicks
        body.querySelectorAll(".sentence-block").forEach(block => {
            block.addEventListener("click", (e) => {
                if (e.target.closest(".word-clickable")) return;
                const visible = block.classList.contains("translation-visible");
                const zh = block.querySelector(".sentence-zh");
                if (visible) { block.classList.remove("translation-visible"); if (zh) zh.style.display = "none"; }
                else { block.classList.add("translation-visible"); if (zh) zh.style.display = "block"; }
            });
        });

        // Exercises
        const exSection = $("exercises-section");
        const exContainer = $("exercises-container");
        if (exSection && exContainer && article.exercises && article.exercises.length > 0) {
            exSection.style.display = "block";
            if (typeof TranslationExercise !== "undefined") TranslationExercise.render(exContainer, article.exercises);
        } else if (exSection) {
            exSection.style.display = "none";
        }

        renderReadingQuestions(article.reading_questions);
        renderCloze(article.cloze);
        setupTTS();

        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    // ═══ Paragraph ═══════════════════════
    function buildParagraph(enPara, zhPara) {
        const enSents = splitEn(enPara), zhSents = splitZh(zhPara);
        if (enSents.length === zhSents.length && enSents.length > 1) {
            return "<p>" + enSents.map((en, i) =>
                '<span class="sentence-block"><span class="sentence-en">' + tokenize(en) + '</span><span class="sentence-zh">' + esc(zhSents[i]) + '</span></span>'
            ).join("") + "</p>";
        }
        return '<p><span class="sentence-block"><span class="sentence-en">' + tokenize(enPara) + '</span><span class="sentence-zh">' + esc(zhPara) + '</span></span></p>';
    }

    function splitEn(t) { return t.split(/(?<=[.!?])\s+/).filter(s => s.trim()); }
    function splitZh(t) { return t.split(/(?<=[。！？])/).filter(s => s.trim()); }
    function tokenize(text) {
        return text.replace(/([a-zA-Z]+(?:[-'][a-zA-Z]+)*)/g, (m) => {
            const lo = m.toLowerCase();
            const keyClass = glossaryMap.has(lo) ? " key-word" : "";
            return '<span class="word-clickable' + keyClass + '" data-word="' + lo + '">' + m + '</span>';
        });
    }

    async function showWordDefinition(word, target) {
        if (typeof Tooltip === "undefined") return;
        const cached = glossaryMap.get(word) || wordDefinitionMap.get(word);
        if (cached) {
            Tooltip.show(cached, target);
            return;
        }

        target.classList.add("is-loading");
        try {
            const resp = await fetch("/api/word/" + encodeURIComponent(word) + "/lookup");
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || "查词失败");
            glossaryMap.set(word, data);
            Tooltip.show(data, target);
        } catch (e) {
            Toast.show(e.message || "暂时无法获取释义", "error");
        } finally {
            target.classList.remove("is-loading");
        }
    }

    function buildGlossaryMap(glossary, wordDefinitions) {
        glossaryMap.clear();
        wordDefinitionMap.clear();
        for (const entry of (wordDefinitions || [])) {
            wordDefinitionMap.set(entry.word.toLowerCase(), entry);
        }
        for (const g of (glossary || [])) {
            const key = g.word.toLowerCase();
            glossaryMap.set(key, g);
            // Article-specific meanings take priority over dictionary meanings.
            wordDefinitionMap.set(key, g);
        }
    }

    function setupGlossary(glossary) {
        const strip = $("glossary-strip");
        const chips = $("glossary-chips");
        const countEl = $("glossary-count");
        if (strip && chips && glossary && glossary.length > 0) {
            strip.style.display = "block";
            if (countEl) countEl.textContent = glossary.length;
            chips.innerHTML = glossary.map(g =>
                '<span class="glossary-chip" data-word="' + esc(g.word.toLowerCase()) + '">' +
                esc(g.word) + '<span class="chip-pos">' + esc(g.part_of_speech || "") + '</span></span>'
            ).join("");
            chips.querySelectorAll(".glossary-chip").forEach(chip => {
                chip.addEventListener("click", (e) => {
                    e.stopPropagation();
                    const entry = glossaryMap.get(chip.dataset.word);
                    if (entry && typeof Tooltip !== "undefined") Tooltip.show(entry, chip);
                });
            });
        } else if (strip) {
            strip.style.display = "none";
        }
    }

    // ═══ Reading Questions ══════════════
    function renderReadingQuestions(questions) {
        const section = $("questions-section");
        const container = $("questions-container");
        if (!section || !container || !questions || questions.length === 0) {
            if (section) section.style.display = "none";
            return;
        }
        section.style.display = "block";

        const typeNames = { main_idea: "主旨大意", detail: "事实细节", inference: "推理判断", vocabulary: "词义猜测", attitude: "观点态度" };
        const allAnswered = questions.every(q => q.user_answer);

        container.innerHTML = questions.map((q, i) => {
            const answered = !!q.user_answer;
            const correct = q.is_correct === 1;
            const itemClass = answered ? (correct ? "q-correct" : "q-wrong") : "";
            return '<div class="question-item ' + itemClass + '" data-qid="' + q.id + '">'
                + '<span class="q-type-badge q-type-' + q.question_type + '">' + (typeNames[q.question_type] || q.question_type) + '</span>'
                + '<div class="q-stem">' + (i + 1) + '. ' + esc(q.question_text) + '</div>'
                + '<div class="q-options">' + ["A","B","C","D"].map(opt => {
                    const optClass = getOptClass(q, opt, answered);
                    return '<div class="q-opt ' + optClass + '" data-opt="' + opt + '"><span class="q-opt-label">' + opt + '.</span><span>' + esc(q["option_" + opt.toLowerCase()] || "") + '</span></div>';
                }).join("") + '</div>'
                + (answered ? '<div class="q-explanation q-expl-' + (correct ? 'correct' : 'wrong') + ' visible"><strong>' + (correct ? '✓ 正确' : '✗ 错误') + '</strong>' + (q.user_answer !== q.correct_answer ? ' <span style="color:var(--ink-muted)">(你选了 ' + q.user_answer + '，正确答案 ' + esc(q.correct_answer || '') + ')</span>' : '') + '<br><br>' + esc(q.explanation_cn || "") + '</div>' : '')
                + '</div>';
        }).join("");

        // Option clicks
        container.querySelectorAll(".q-opt").forEach(opt => {
            opt.addEventListener("click", () => {
                const item = opt.closest(".question-item");
                if (!item) return;
                item.querySelectorAll(".q-opt").forEach(o => o.classList.remove("selected"));
                opt.classList.add("selected");
                item.dataset.chosen = opt.dataset.opt;
            });
        });

        if (!allAnswered) {
            const btnRow = document.createElement("div");
            btnRow.className = "q-submit-row";
            btnRow.innerHTML = '<button class="submit-btn" id="q-submit-btn">提交全部答案</button><span class="score-label" id="q-submit-hint">请选完所有 ' + questions.length + ' 题后提交</span>';
            container.appendChild(btnRow);

            $("q-submit-btn").addEventListener("click", async () => {
                const answers = {};
                container.querySelectorAll(".question-item").forEach(item => {
                    if (item.dataset.chosen) answers[item.dataset.qid] = item.dataset.chosen;
                });
                if (Object.keys(answers).length < questions.length) {
                    Toast.show("请先回答所有问题", "error");
                    return;
                }
                const btn = $("q-submit-btn");
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-sm"></span> 批改中...';
                try {
                    const resp = await fetch("/api/reading/submit", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ article_id: currentArticleId, answers }),
                    });
                    const result = await resp.json();
                    const article = await fetch("/api/article/" + currentArticleId).then(r => r.json());
                    renderReadingQuestions(article.reading_questions);
                    showReadingScoreBanner(result);
                } catch (e) {
                    Toast.show("提交失败", "error");
                    btn.disabled = false;
                }
            });
        }
    }

    function getOptClass(q, opt, answered) {
        if (!answered) return "";
        if (opt === q.correct_answer) return "correct";
        if (opt === q.user_answer && q.user_answer !== q.correct_answer) return "wrong";
        return "";
    }

    function showReadingScoreBanner(result) {
        const container = $("questions-container");
        if (!container) return;
        const existing = container.querySelector(".q-score-banner");
        if (existing) existing.remove();
        const banner = document.createElement("div");
        banner.className = "q-score-banner visible " +
            (result.score >= 80 ? "q-score-great" : result.score >= 60 ? "q-score-ok" : "q-score-poor");
        banner.textContent = "阅读理解得分: " + result.correct_count + "/" + result.total + " (" + result.score + "分)";
        container.insertBefore(banner, container.firstChild);
    }

    // ═══ Cloze ═══════════════════════════
    function renderCloze(cloze) {
        const section = $("cloze-section");
        const container = $("cloze-container");
        if (!section || !container || !cloze || !Array.isArray(cloze.blanks) || cloze.blanks.length === 0) {
            if (section) section.style.display = "none";
            return;
        }
        section.style.display = "block";

        const userAnswers = cloze.user_answers || {};
        const submitted = cloze.score !== undefined && cloze.score !== null;
        const blanks = cloze.blanks.slice().sort((a, b) => a.blank_index - b.blank_index);
        const blankSet = new Map(blanks.map(b => [b.blank_index, b]));

        let passageHtml = esc(cloze.passage_text);
        passageHtml = passageHtml.replace(/__(\d+)__/g, (m, num) => {
            const bi = parseInt(num);
            const b = blankSet.get(bi);
            if (!b) return m;
            const ua = userAnswers[bi] || "";
            const correct = submitted && ua === b.correct_answer;
            const wrong = submitted && ua !== b.correct_answer;
            const cls = "cloze-blank" + (ua ? " filled" : "") + (correct ? " correct" : "") + (wrong ? " wrong" : "");
            return '<span class="' + cls + '" data-blank="' + bi + '">' + esc(ua || "___") + '</span>';
        });

        const questionHtml = blanks.map((b, index) => {
            const bi = b.blank_index;
            const answer = userAnswers[bi] || userAnswers[String(bi)] || "";
            const optionHtml = (b.options || []).map((opt, optIndex) => {
                const selected = !submitted && answer === opt;
                const correct = submitted && opt === b.correct_answer;
                const wrong = submitted && opt === answer && answer !== b.correct_answer;
                const cls = "cloze-option" + (selected ? " selected" : "") + (correct ? " correct" : "") + (wrong ? " wrong" : "");
                return '<button type="button" class="' + cls + '" data-blank="' + bi + '" data-option-index="' + optIndex + '">' +
                    '<span class="cloze-option-letter">' + String.fromCharCode(65 + optIndex) + '</span>' +
                    '<span>' + esc(opt) + '</span></button>';
            }).join("");
            const explanation = submitted ? '<div class="cloze-explanation">' + esc(b.explanation_cn || "") + '</div>' : "";
            return '<div class="cloze-question" data-blank="' + bi + '">' +
                '<div class="cloze-question-head"><span class="cloze-question-number">第 ' + (index + 1) + ' 空</span><span class="cloze-question-hint">选择最合适的词</span></div>' +
                '<div class="cloze-options">' + optionHtml + '</div>' + explanation +
                '</div>';
        }).join("");

        const scoreHtml = submitted ? '<div class="q-score-banner visible ' +
            (cloze.score >= 8 ? "q-score-great" : cloze.score >= 6 ? "q-score-ok" : "q-score-poor") +
            '">完形填空得分：' + cloze.score + "/" + blanks.length + '</div>' : "";

        container.innerHTML = scoreHtml +
            '<div class="cloze-workspace">' +
                '<div class="cloze-passage-column"><div class="cloze-passage" id="cloze-passage">' + passageHtml + '</div></div>' +
                '<div class="cloze-question-column">' +
                    '<div class="cloze-question-list" aria-label="完形填空题目">' + questionHtml + '</div>' +
                    (submitted ? '' : '<div class="cloze-submit-row"><button class="submit-btn" id="cloze-submit-btn">提交完形填空</button><span class="score-label">共 ' + blanks.length + ' 空</span></div>') +
                '</div>' +
            '</div>';

        function syncChoice(blankIndex, answer) {
            const blank = container.querySelector('.cloze-blank[data-blank="' + blankIndex + '"]');
            if (blank) {
                blank.textContent = answer;
                blank.classList.add("filled");
            }
            container.querySelectorAll('.cloze-option[data-blank="' + blankIndex + '"]').forEach(option => {
                const b = blankSet.get(blankIndex);
                const value = b.options[parseInt(option.dataset.optionIndex)];
                option.classList.toggle("selected", value === answer);
            });
        }

        container.querySelectorAll(".cloze-option").forEach(option => {
            option.addEventListener("click", () => {
                if (submitted) return;
                const bi = parseInt(option.dataset.blank);
                const b = blankSet.get(bi);
                const value = b && b.options[parseInt(option.dataset.optionIndex)];
                if (!b || !value) return;
                userAnswers[bi] = value;
                syncChoice(bi, value);
            });
        });

        container.querySelectorAll(".cloze-blank").forEach(blank => {
            blank.addEventListener("click", () => {
                const question = container.querySelector('.cloze-question[data-blank="' + blank.dataset.blank + '"]');
                if (question) question.scrollIntoView({ behavior: "smooth", block: "center" });
            });
        });

        const submitBtn = $("cloze-submit-btn");
        if (submitBtn) {
            submitBtn.addEventListener("click", async () => {
                const allFilled = blanks.every(b => userAnswers[b.blank_index]);
                if (!allFilled) { Toast.show("请先完成所有空格", "error"); return; }
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<span class="spinner-sm"></span> 批改中...';
                try {
                    const resp = await fetch("/api/cloze/submit", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ cloze_id: cloze.id, answers: userAnswers }),
                    });
                    if (!resp.ok) {
                        const err = await resp.json();
                        throw new Error(err.error || "提交失败");
                    }
                    const article = await fetch("/api/article/" + currentArticleId).then(r => r.json());
                    renderCloze(article.cloze);
                } catch (e) {
                    Toast.show(e.message || "提交失败", "error");
                    submitBtn.disabled = false;
                }
            });
        }
    }

    // ═══ Archive ═════════════════════════
    async function loadArchive() {
        try {
            const sel = $("archive-select");
            if (!sel) return;
            const resp = await fetch("/api/articles");
            const articles = await resp.json();
            for (const a of articles) {
                const opt = document.createElement("option");
                opt.value = a.id;
                opt.textContent = fmtDate(a.created_at).replace(/年|月|日/g, "/");
                sel.appendChild(opt);
            }
        } catch (e) { /* ignore */ }
    }

    function setupArchiveChange() {
        const sel = $("archive-select");
        if (!sel) return;
        sel.addEventListener("change", async function () {
            const id = this.value;
            if (!id) return;
            showLoading(true);
            try {
                const resp = await fetch("/api/article/" + id);
                if (!resp.ok) throw new Error("Not found");
                renderArticle(await resp.json());
            } catch (e) { showError("加载历史文章失败。"); }
            finally { showLoading(false); }
        });
    }

    // ═══ Stats modal ════════════════════
    function setupStatsModal() {
        const btn = $("stats-btn");
        const modal = $("stats-modal");
        const close = $("modal-close");
        if (!btn || !modal) return;

        btn.addEventListener("click", async () => {
            modal.style.display = "flex";
            const body = $("stats-body");
            if (!body) return;
            body.innerHTML = '<div class="loading-area"><div class="skeleton skeleton-line"></div></div>';
            try {
                const resp = await fetch("/api/stats");
                const s = await resp.json();
                const labels = { unfamiliar: "未掌握", learning: "学习中", mastered: "已掌握" };
                body.innerHTML = `
                    <div class="stats-grid">
                        <div class="stat-card"><div class="stat-value">${s.unique_words}</div><div class="stat-label">生词总数</div></div>
                        <div class="stat-card"><div class="stat-value">${s.total_lookups}</div><div class="stat-label">总查询次数</div></div>
                        <div class="stat-card"><div class="stat-value">${s.total_exercises}</div><div class="stat-label">翻译练习</div></div>
                        <div class="stat-card"><div class="stat-value">${s.avg_score || "-"}</div><div class="stat-label">平均得分</div></div>
                    </div>
                    ${s.top_words && s.top_words.length ? '<div class="stats-divider">最常查询的单词</div><div class="top-word-tags">' + s.top_words.map(w => '<span class="word-tag">' + esc(w.word) + '<span class="wt-count">×' + w.count + '</span><span class="wt-status">' + (labels[w.status] || w.status) + '</span></span>').join("") + '</div>' : ""}`;
            } catch (e) {
                body.innerHTML = '<p style="color:var(--ink-muted);text-align:center;">加载失败</p>';
            }
        });
        close.addEventListener("click", () => modal.style.display = "none");
        modal.addEventListener("click", (e) => { if (e.target === modal) modal.style.display = "none"; });
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && modal.style.display === "flex") modal.style.display = "none";
        });
    }

    // ═══ States ═══════════════════════════
    function showNoArticle() {
        hideLoading(); hideArticleSections();
        const area = $("error-area");
        if (!area) return;
        area.style.display = "block";
        area.innerHTML = `
            <div style="text-align:center;padding:24px 0;">
                <div style="font-size:3rem;margin-bottom:12px;">📰</div>
                <p style="font-size:1rem;font-weight:600;margin-bottom:6px;">今日文章尚未生成</p>
                <p style="color:var(--ink-muted);font-size:0.88rem;margin-bottom:18px;">等待每日 8:00 自动生成，或点击下方手动生成</p>
                <button class="btn-primary" id="generate-btn">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                    立即生成
                </button>
                <span id="gen-status" style="display:block;margin-top:10px;font-size:0.82rem;color:var(--ink-muted);"></span>
            </div>`;
        const btn = $("generate-btn");
        if (!btn) return;
        btn.addEventListener("click", async function () {
            this.disabled = true;
            this.innerHTML = '<span class="spinner-sm"></span> AI 创作中...';
            const status = $("gen-status");
            if (status) status.textContent = "预计 30-60 秒，包含文章、阅读题、完形填空";
            try {
                const r = await fetch("/api/generate", { method: "POST" });
                if (r.ok) { if (status) status.textContent = "生成成功，正在加载..."; location.reload(); }
                else { const err = await r.json(); throw new Error(err.error || "未知错误"); }
            } catch (e) {
                if (status) status.textContent = "失败: " + e.message;
                this.disabled = false;
                this.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> 重试';
            }
        });
    }

    function showError(msg) {
        hideLoading(); hideArticleSections();
        const area = $("error-area");
        if (!area) return;
        area.style.display = "block";
        area.innerHTML = '<div style="text-align:center;padding:24px 0;"><p style="color:var(--red);">' + esc(msg) + '</p><button class="btn-ghost" onclick="location.reload()" style="margin-top:12px;">刷新页面</button></div>';
    }

    function hideError() {
        const area = $("error-area");
        if (area) area.style.display = "none";
    }

    // ═══ Helpers ══════════════════════════
    function setText(id, text) { const el = $(id); if (el) el.textContent = text; }
    function showLoading(show) { const el = $("loading"); if (el) el.style.display = show ? "block" : "none"; }
    function hideLoading() { const el = $("loading"); if (el) el.style.display = "none"; }
    function hideArticleSections() {
        ["article-section", "exercises-section", "questions-section", "cloze-section"].forEach(id => {
            const el = $(id);
            if (el) el.style.display = "none";
        });
    }
    function fmtDate(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        return d.getFullYear() + "年" + (d.getMonth() + 1) + "月" + d.getDate() + "日";
    }
    function esc(s) {
        if (!s) return "";
        const d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }
})();
