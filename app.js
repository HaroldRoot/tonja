window.addEventListener('DOMContentLoaded', () => {

    const inputText = document.getElementById('inputText');
    const outputText = document.getElementById('outputText');
    const convertButton = document.getElementById('convertButton');
    const copyButton = document.getElementById('copyButton');
    const clearButton = document.getElementById('clearButton');
    const inputCount = document.getElementById('inputCount');
    const outputCount = document.getElementById('outputCount');
    const toast = document.getElementById('toast');

    // charMap: { 原字: [候选字, ...] }，由 build.py 生成。
    let charMap = null;
    let toastTimer;

    const convertLabelHTML = '<span class="btn__icon" aria-hidden="true">→</span><span>开始随机转换</span>';

    function showToast(message, type = 'ok') {
        if (!toast) return;
        toast.textContent = message;
        toast.classList.remove('toast--ok', 'toast--err');
        toast.classList.add(type === 'err' ? 'toast--err' : 'toast--ok');
        toast.classList.add('is-visible');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.remove('is-visible'), 2400);
    }

    function updateCounts() {
        // 用展开运算符按码点计数，正确处理可能的代理对。
        inputCount.textContent = `${[...inputText.value].length} 字`;
        outputCount.textContent = `${[...outputText.value].length} 字`;
    }

    async function loadMapping() {
        try {
            const response = await fetch('mapping.json');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            charMap = await response.json();

            convertButton.disabled = false;
            convertButton.innerHTML = convertLabelHTML;
        } catch (error) {
            console.error('加载 mapping.json 失败:', error);
            convertButton.disabled = true;
            convertButton.textContent = '加载失败';
            showToast('字形映射文件加载失败，请刷新页面重试。', 'err');
        }
    }

    // 每次转换对每个可替换字随机挑一个候选——重复点击「开始转换」会得到不同结果。
    function convertText() {
        if (!charMap) {
            showToast('映射尚未加载完成，请稍候。', 'err');
            return;
        }
        if (!inputText.value.trim()) {
            showToast('输入内容为空。', 'err');
            inputText.focus();
            return;
        }

        const chars = [...inputText.value];
        let replaced = 0;
        for (let i = 0; i < chars.length; i++) {
            const candidates = charMap[chars[i]];
            if (candidates && candidates.length) {
                chars[i] = candidates[(Math.random() * candidates.length) | 0];
                replaced++;
            }
        }
        outputText.value = chars.join('');
        updateCounts();

        if (replaced === 0) {
            showToast('没有可替换的字，已原样输出。', 'err');
        }
    }

    function copyOutput() {
        if (!outputText.value) {
            showToast('输出内容为空，无需复制。', 'err');
            return;
        }
        const done = () => showToast('已复制到剪贴板');
        const fail = () => showToast('复制失败，请手动选择并复制。', 'err');

        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(outputText.value).then(done).catch(() => {
                outputText.select();
                try { document.execCommand('copy') ? done() : fail(); } catch { fail(); }
            });
        } else {
            outputText.select();
            try { document.execCommand('copy') ? done() : fail(); } catch { fail(); }
        }
    }

    function clearInput() {
        if (!inputText.value && !outputText.value) {
            inputText.focus();
            return;
        }
        inputText.value = '';
        outputText.value = '';
        updateCounts();
        inputText.focus();
        showToast('已清空');
    }

    convertButton.disabled = true;
    convertButton.textContent = '加载中…';

    convertButton.addEventListener('click', convertText);
    copyButton.addEventListener('click', copyOutput);
    clearButton.addEventListener('click', clearInput);
    inputText.addEventListener('input', updateCounts);

    inputText.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            convertText();
        }
    });

    const more = document.getElementById('more');
    const moreButton = document.getElementById('moreButton');
    const moreMenu = document.getElementById('moreMenu');

    function setMoreOpen(open) {
        more.classList.toggle('is-open', open);
        moreButton.setAttribute('aria-expanded', String(open));
    }

    moreButton.addEventListener('click', (e) => {
        e.stopPropagation();
        setMoreOpen(!more.classList.contains('is-open'));
    });

    document.addEventListener('click', (e) => {
        if (!more.contains(e.target)) setMoreOpen(false);
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && more.classList.contains('is-open')) {
            setMoreOpen(false);
            moreButton.focus();
        }
    });

    moreMenu.addEventListener('click', (e) => {
        if (e.target.closest('.more__item')) setMoreOpen(false);
    });

    updateCounts();
    loadMapping();

    initTitleTypewriter();
});

// 标题打字机：在多条标语之间轮换——逐字打出、停留、再逐字删除，右侧光标由 CSS 闪烁。
// 每条标语拆成若干片段，em:true 的片段用 <em> 包裹（强调色）。
function initTitleTypewriter() {
    const el = document.getElementById('titleText');
    if (!el) return;

    const phrases = [
        [{ text: '面对 AI 审查，我们' }, { text: '并非无计可施。', em: true }],
        [{ text: '生成随机偏旁，制造' }, { text: '认知污染。', em: true }],
    ];

    // 尊重「减少动态效果」偏好：保留 HTML 里的首条静态标语，不打字、不轮换。
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
    }

    const TYPE_MS = 110;     // 每打出一个字的间隔
    const ERASE_MS = 55;     // 每删除一个字的间隔
    const HOLD_MS = 2200;    // 打完后停留时长
    const GAP_MS = 500;      // 删完后切换到下一条前的空档

    // 把一条标语展开成 [{ch, em}, ...] 的逐字序列，方便按长度截取并重建 HTML。
    const expand = (segs) => segs.flatMap(s => [...s.text].map(ch => ({ ch, em: !!s.em })));

    const render = (chars) => {
        let html = '';
        let inEm = false;
        for (const { ch, em } of chars) {
            if (em && !inEm) { html += '<em>'; inEm = true; }
            else if (!em && inEm) { html += '</em>'; inEm = false; }
            html += ch.replace('&', '&amp;').replace('<', '&lt;');
        }
        if (inEm) html += '</em>';
        el.innerHTML = html;
    };

    // phase: 'type' | 'hold' | 'erase' | 'gap'。首条已在 HTML 中打好，直接从 hold 开始。
    let pi = 0;
    let i = expand(phrases[0]).length;

    const step = (phase) => {
        const full = expand(phrases[pi]);
        if (phase === 'type') {
            render(full.slice(0, i));
            if (i < full.length) { i++; setTimeout(() => step('type'), TYPE_MS); }
            else setTimeout(() => step('erase'), HOLD_MS);
        } else if (phase === 'erase') {
            render(full.slice(0, i));
            if (i > 0) { i--; setTimeout(() => step('erase'), ERASE_MS); }
            else { pi = (pi + 1) % phrases.length; setTimeout(() => step('type'), GAP_MS); }
        }
    };

    setTimeout(() => step('erase'), HOLD_MS);
}
