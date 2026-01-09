const { FIELD_WRAPPER_SELECTOR } = require('./get-form-field-wrapper');
const { getVisualLabel, SOURCE_PLACEHOLDER } = require('./get-visual-label');

const SOURCE_HELPER_NEARBY = "HELPER_NEARBY";
const SOURCE_HELPER_DISTANT = "HELPER_DISTANT";
const SOURCE_ARIA_DESCRIBEDBY = "ARIA_DESCRIBEDBY";
const SOURCE_TITLE = "TITLE";
const SOURCE_NONE = "NONE";

// getHelperText: returns an object representing helper text associated with a form control element
// Preference order: aria-describedby -> title attribute -> nearby visual helper text
// Helper text must NOT be the visual label or part of the accessible name
const getHelperText = async (el, opts = {}) => {
    const { maxDistance = 300 } = opts;

    // Get the visual label text to exclude from helper text
    let visualLabelText = '';
    let visualLabelIsPlaceholder = false;
    try {
        const vLabel = await getVisualLabel(el);
        if (vLabel && typeof vLabel === 'object') {
            if (vLabel.text) {
                visualLabelText = (vLabel.text || '').trim();
            }
            visualLabelIsPlaceholder = vLabel.source === SOURCE_PLACEHOLDER;
        }
    } catch (_) {}

    const helper = await el.evaluate((el, args) => {
        const {
            FIELD_WRAPPER_SELECTOR,
            maxDistance,
            visualLabelText,
            SOURCE_HELPER_NEARBY,
            SOURCE_HELPER_DISTANT,
            SOURCE_ARIA_DESCRIBEDBY,
            SOURCE_TITLE,
            SOURCE_NONE,
            visualLabelIsPlaceholder
        } = args;

        function isVisible(node) {
            return window.axe.commons.dom.isVisible(node, false, true);
        }

        function textOf(node) {
            if (!node) return '';
            return (node.textContent || '').replace(/\s+/g, ' ').trim();
        }

        // Accessible name to exclude from helper text
        const accessibleName = (window.axe.commons.text.accessibleText(el) || '').trim();

        function isNameOrLabelText(txt) {
            if (!txt) return true; // treat empty as not helpful
            const t = txt.trim();
            if (!t) return true;
            const name = accessibleName;
            const label = visualLabelText || '';
            // Exclude if matches or is contained within name or label
            if (t === name || t === label) return true;
            if (name && (name.includes(t))) return true;
            if (label && (label.includes(t))) return true;
            return false;
        }

        function looksLikeError(node) {
            if (!node) return false;
            const role = node.getAttribute && node.getAttribute('role');
            if (role && (role === 'alert')) return true;
            if (node.hasAttribute && node.hasAttribute('aria-live')) return true;
            const cls = (node.className || '').toString().toLowerCase();
            if (/(error|invalid|validation)/.test(cls)) return true;
            return false;
        }

        function looksLikeHelper(node) {
            if (!node) return false;
            const cls = (node.className || '').toString().toLowerCase();
            if (/(hint|help|description|instructions|note|assist|guidance)/.test(cls)) return true;
            if (node.tagName === 'SMALL') return true; // often used for hints
            const role = node.getAttribute && node.getAttribute('role');
            if (role === 'tooltip') return true;
            return false;
        }

        // 1) aria-describedby
        const parts = [];
        const describedby = el.getAttribute && el.getAttribute('aria-describedby');
        if (describedby) {
            for (const id of describedby.split(/\s+/)) {
                const target = document.getElementById(id);
                if (target && isVisible(target) && !looksLikeError(target)) {
                    const t = textOf(target);
                    if (t && !isNameOrLabelText(t)) parts.push(t);
                }
            }
        }
        if (parts.length) return { text: parts.join(' '), source: SOURCE_ARIA_DESCRIBEDBY };

        // 2) title attribute
        const titleAttr = el.getAttribute && el.getAttribute('title');
        if (titleAttr && !isNameOrLabelText(titleAttr)) {
            return { text: titleAttr.trim(), source: SOURCE_TITLE };
        }

        // 3) Nearby visual helper text within the field wrapper (and placeholder when not used as label)
        const wrapper = el.closest(FIELD_WRAPPER_SELECTOR) || document.body;
        const candidates = [];
        const inputRect = el.getBoundingClientRect();

        // Treat placeholder as helper text when it is not acting as the visual label
        try {
            const placeholderAttr = el.getAttribute && el.getAttribute('placeholder');
            const pt = (placeholderAttr || '').replace(/\s+/g, ' ').trim();
            if (!visualLabelIsPlaceholder && pt && pt.length > 1) {
                // Ensure it's not identical to the visual label text
                if (!visualLabelText || pt !== visualLabelText) {
                    candidates.push({ node: el, text: pt, rect: inputRect, distance: 0, dy: 0 });
                }
            }
        } catch (_) {}

        function isFollowing(node, ref) {
            try {
                return !!(ref.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING);
            } catch (_) {
                return false;
            }
        }

        const walker = document.createTreeWalker(wrapper, NodeFilter.SHOW_ELEMENT, {
            acceptNode(node) {
                if (node === el) return NodeFilter.FILTER_REJECT;
                if (!isVisible(node)) return NodeFilter.FILTER_REJECT;
                if (node.contains(el)) return NodeFilter.FILTER_REJECT;
                if (looksLikeError(node)) return NodeFilter.FILTER_REJECT;
                const txt = textOf(node);
                if (!txt) return NodeFilter.FILTER_REJECT;
                if (isNameOrLabelText(txt)) return NodeFilter.FILTER_REJECT;
                // Prefer elements that look like helper text
                return looksLikeHelper(node) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
            }
        }, false);

        while (walker.nextNode()) {
            const node = walker.currentNode;
            const rect = node.getBoundingClientRect();
            const dx = (rect.left + rect.right) / 2 - (inputRect.left + inputRect.right) / 2;
            const dy = (rect.top + rect.bottom) / 2 - (inputRect.top + inputRect.bottom) / 2;
            const distance = Math.hypot(dx, dy);
            candidates.push({ node, text: textOf(node), rect, distance, dy });
        }

        if (candidates.length === 0) {
            // Second pass: allow generic nearby text below the control if not name/label
            const walker2 = document.createTreeWalker(wrapper, NodeFilter.SHOW_ELEMENT, {
                acceptNode(node) {
                    if (node === el) return NodeFilter.FILTER_REJECT;
                    if (!isVisible(node)) return NodeFilter.FILTER_REJECT;
                    if (node.contains(el)) return NodeFilter.FILTER_REJECT;
                    if (looksLikeError(node)) return NodeFilter.FILTER_REJECT;
                    const txt = textOf(node);
                    if (!txt || isNameOrLabelText(txt)) return NodeFilter.FILTER_REJECT;
                    return NodeFilter.FILTER_ACCEPT;
                }
            }, false);

            while (walker2.nextNode()) {
                const node = walker2.currentNode;
                const rect = node.getBoundingClientRect();
                const dx = (rect.left + rect.right) / 2 - (inputRect.left + inputRect.right) / 2;
                const dy = (rect.top + rect.bottom) / 2 - (inputRect.top + inputRect.bottom) / 2;
                const distance = Math.hypot(dx, dy);
                candidates.push({ node, text: textOf(node), rect, distance, dy });
            }
        }

        if (candidates.length === 0) {
            return { text: '', source: SOURCE_NONE };
        }

        // Helper text aggregation: include all nearby helper texts within maxDistance, no below preference
        function byDomOrder(a, b) {
            try {
                const pos = a.node.compareDocumentPosition(b.node);
                if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1; // a before b
                if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;  // a after b
            } catch (_) {}
            return a.distance - b.distance;
        }

        function isSingleCharText(txt) {
            return ((txt || '').trim().length === 1);
        }

        function joinNonTrivial(items) {
            const out = [];
            for (const t of items) {
                const s = (t || '').trim();
                if (!s) continue;
                if (isSingleCharText(s)) continue; // omit single-character helper text
                out.push(s);
            }
            return out.join(' ');
        }

        const within = candidates.filter(c => c.distance <= maxDistance);
        if (within.length > 0) {
            const texts = within.sort(byDomOrder).map(c => c.text);
            const combined = joinNonTrivial(texts);
            if (combined) return { text: combined, source: SOURCE_HELPER_NEARBY };
            // if all within are trivial, fall through to distant aggregate
        }

        // Fallback: include all distant helper texts
        const texts = candidates.sort((a, b) => a.distance - b.distance).map(c => c.text);
        const combined = joinNonTrivial(texts);
        return combined ? { text: combined, source: SOURCE_HELPER_DISTANT } : { text: '', source: SOURCE_NONE };
    }, {
        FIELD_WRAPPER_SELECTOR,
        maxDistance,
        visualLabelText,
        SOURCE_HELPER_NEARBY,
        SOURCE_HELPER_DISTANT,
        SOURCE_ARIA_DESCRIBEDBY,
        SOURCE_TITLE,
        SOURCE_NONE,
        visualLabelIsPlaceholder
    });

    return helper || '';
}

module.exports.getHelperText = getHelperText;
module.exports.SOURCE_HELPER_NEARBY = SOURCE_HELPER_NEARBY;
module.exports.SOURCE_HELPER_DISTANT = SOURCE_HELPER_DISTANT;
module.exports.SOURCE_ARIA_DESCRIBEDBY = SOURCE_ARIA_DESCRIBEDBY;
module.exports.SOURCE_TITLE = SOURCE_TITLE;
module.exports.SOURCE_NONE = SOURCE_NONE;