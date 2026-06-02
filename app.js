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

    const convertLabelHTML = '<span class="btn__icon" aria-hidden="true">→</span><span>开始转换</span>';

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
});
