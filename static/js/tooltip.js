const Tooltip = (() => {
    const el = document.getElementById("word-tooltip");
    const inner = el.querySelector(".tooltip-inner");
    const arrow = el.querySelector(".tooltip-arrow");
    let currentWord = null;
    let currentTarget = null;
    let onMarkUnfamiliar = null;

    function setMarkCallback(cb) {
        onMarkUnfamiliar = cb;
    }

    function show(wordData, targetEl) {
        currentWord = wordData;
        currentTarget = targetEl;

        let html = `
            <div class="tt-word-row">
                <span class="tt-word">${esc(wordData.word)}</span>
                ${wordData.part_of_speech ? `<span class="tt-pos">${esc(wordData.part_of_speech)}</span>` : ""}
            </div>
            <div class="tt-meaning">${esc(wordData.chinese_meaning)}</div>
            ${wordData.sentence_example ? `<div class="tt-example">${esc(wordData.sentence_example)}</div>` : ""}
            <div class="tt-footer">
                ${wordData.difficulty_level ? `<span class="tt-level">${esc(wordData.difficulty_level)}</span>` : ""}
                <button class="tt-mark-btn" id="tt-mark-btn" title="标记为不熟悉的单词">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
                    不熟悉
                </button>
            </div>`;
        inner.innerHTML = html;

        // Bind mark button
        const btn = inner.querySelector("#tt-mark-btn");
        if (btn) {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                if (onMarkUnfamiliar && currentWord) {
                    onMarkUnfamiliar(currentWord.word);
                    btn.textContent = "已标记";
                    btn.disabled = true;
                    btn.style.opacity = "0.6";
                    btn.style.cursor = "default";
                }
            });
        }

        // Position
        el.style.display = "block";
        el.classList.add("visible");
        el.style.visibility = "hidden";

        const rect = targetEl.getBoundingClientRect();
        const scrollTop = window.scrollY || document.documentElement.scrollTop;
        const tw = el.offsetWidth;
        const th = el.offsetHeight;

        let top = rect.top + scrollTop - th - 14;
        let left = rect.left + rect.width / 2 - tw / 2;
        let showAbove = true;

        if (top < scrollTop + 10) {
            top = rect.bottom + scrollTop + 14;
            showAbove = false;
        }
        if (left < 10) left = 10;
        if (left + tw > window.innerWidth - 10) {
            left = window.innerWidth - tw - 10;
        }

        el.style.top = top + "px";
        el.style.left = left + "px";

        if (showAbove) {
            arrow.style.display = "block";
            arrow.style.borderTop = "8px solid var(--ink)";
            arrow.style.borderBottom = "none";
        } else {
            arrow.style.display = "block";
            arrow.style.borderBottom = "8px solid #0f172a";
            arrow.style.borderTop = "none";
        }

        el.style.visibility = "visible";
    }

    function hide() {
        el.classList.remove("visible");
        currentWord = null;
        currentTarget = null;
    }

    function getCurrentWord() { return currentWord; }

    document.addEventListener("click", (e) => {
        if (!el.contains(e.target) && !e.target.closest(".word-clickable") && !e.target.closest(".glossary-chip")) {
            hide();
        }
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
    window.addEventListener("scroll", () => { if (currentWord) hide(); }, { passive: true });

    function esc(s) {
        if (!s) return "";
        const d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    return { show, hide, getCurrentWord, setMarkCallback };
})();
