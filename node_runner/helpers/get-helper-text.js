const {
    FIELD_WRAPPER_SELECTOR,
    PRIMARY_SEMANTIC_FIELD_WRAPPER_SELECTOR,
    SECONDARY_SEMANTIC_FIELD_WRAPPER_SELECTOR,
    FALLBACK_FIELD_WRAPPER_SELECTOR,
} = require('./get-form-field-wrapper');
const { getAccessibleDescription: getAccessibilityTreeDescription } = require('./get-accessibility-tree');
const { getVisualLabel, SOURCE_PLACEHOLDER } = require('./get-visual-label');

const SOURCE_HELPER_NEARBY = "HELPER_NEARBY";
const SOURCE_ARIA_DESCRIBEDBY = "ARIA_DESCRIBEDBY";
const SOURCE_ARIA_DESCRIPTION = "ARIA_DESCRIPTION";
const SOURCE_ARIA_PLACEHOLDER = "ARIA_PLACEHOLDER";
const SOURCE_PLACEHOLDER_ATTR = "PLACEHOLDER_ATTR";
const SOURCE_TITLE = "TITLE";
const SOURCE_CSS_PLACEHOLDER = "CSS_PLACEHOLDER";
const SOURCE_NONE = "NONE";

// getHelperText: returns all potential helper text associated with a form control element
// Looks for text sourced from aria-describedby, aria-description, title attribute, nearby visual text
// (including single-character indicators like "*") and placeholder when not used as label.
// Helper text must NOT be the visual label.
// Returns: Array<{ text: string, source: string }>
const getHelperText = async (el, opts = {}) => {
    // Get the visual label text so we can exclude it from helper text
    let visualLabelText = '';
    let visualLabelIsPlaceholder = false;

    const vLabel = await getVisualLabel(el);
    if (vLabel && typeof vLabel === 'object') {
        if (vLabel.text) {
            visualLabelText = String(vLabel.text).trim();
        }
        visualLabelIsPlaceholder = vLabel.source === SOURCE_PLACEHOLDER;
    }

    const helper = await el.evaluate((el, args) => {
        const {
            FIELD_WRAPPER_SELECTOR,
            PRIMARY_SEMANTIC_FIELD_WRAPPER_SELECTOR,
            SECONDARY_SEMANTIC_FIELD_WRAPPER_SELECTOR,
            FALLBACK_FIELD_WRAPPER_SELECTOR,
            visualLabelText,
            SOURCE_HELPER_NEARBY,
            SOURCE_ARIA_DESCRIBEDBY,
            SOURCE_ARIA_DESCRIPTION,
            SOURCE_ARIA_PLACEHOLDER,
            SOURCE_PLACEHOLDER_ATTR,
            SOURCE_TITLE,
            SOURCE_CSS_PLACEHOLDER,
            SOURCE_NONE,
            visualLabelIsPlaceholder
        } = args;

        const labelLower = (visualLabelText || '').toLowerCase();
        const SUPPLEMENTARY_CLASS_RE = /\b(desc|description|helper|help-text|helper-text|hint|tooltip|supporting|assistive|option-desc|field-note|field-description)\b/;

        function normText(s) {
            return (s || '').replace(/\s+/g, ' ').trim();
        }

        function looksLikeSupplementary(node) {
            if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
            const role = (node.getAttribute && (node.getAttribute('role') || '')).toLowerCase();
            if (role && (role === 'tooltip' || role === 'note' || role === 'status' || role === 'alert')) {
                return true;
            }
            if (node.hasAttribute && (node.hasAttribute('aria-live') || node.hasAttribute('aria-description'))) {
                return true;
            }
            const cls = (node.className || '').toString().toLowerCase();
            return SUPPLEMENTARY_CLASS_RE.test(cls);
        }

        function hasSupplementaryAncestorWithinLabel(node) {
            if (!node || !node.closest) return false;
            const label = node.closest('label');
            if (!label) return false;

            let current = node;
            while (current && current !== label) {
                if (looksLikeSupplementary(current)) {
                    return true;
                }
                current = current.parentElement;
            }

            return false;
        }

        function splitWords(s) {
            return (s || '').split(/\s+/).map(w => w.trim()).filter(Boolean);
        }

        const STOP_WORDS = new Set([
            'enter',
            'type',
            'provide',
            'input',
            'please',
            'your',
            'the',
            'a',
            'an'
        ]);

        // Heuristic: is this text node mostly just the visual label (or a small fragment of it)?
        function isMostlyFromLabel(txtLower, labelLower) {
            if (!txtLower || !labelLower) return false;

            // Very short / punctuation-like text that appears in the label (e.g. "*")
            if (txtLower.length <= 2 && labelLower.includes(txtLower)) {
                return true;
            }

            const txtWords = splitWords(txtLower);
            const labelWords = splitWords(labelLower);
            if (!txtWords.length || !labelWords.length) return false;

            const labelSet = new Set(labelWords);

            // Remove generic prompt words like "enter", "please", "your"
            const txtContentWords = txtWords.filter(w => !STOP_WORDS.has(w));
            if (!txtContentWords.length) return false;

            let overlap = 0;
            for (const w of txtContentWords) {
                if (labelSet.has(w)) overlap++;
            }

            // If all non-stopword words in this node are label words, and it's short,
            // treat it as label text, not helper text (e.g. "full name", "enter your name").
            if (overlap === txtContentWords.length && txtContentWords.length <= 3) {
                return true;
            }

            return false;
        }

        const helpers = [];

        function addHelper(text, source, nodeForOrder) {
            const t = normText(text);
            if (!t) return;
            helpers.push({ text: t, source, _node: nodeForOrder || null });
        }

        function getPseudoContent(pseudo) {
            try {
                const style = window.getComputedStyle(el, pseudo);
                if (!style) return '';

                let content = style.getPropertyValue('content');
                if (!content || content === 'none' || content === 'normal') return '';

                content = content.trim();

                if ((content.startsWith('"') && content.endsWith('"')) ||
                    (content.startsWith("'") && content.endsWith("'"))) {
                    content = content.slice(1, -1);
                }

                return normText(content);
            } catch (e) {
                return '';
            }
        }

        // --- 0. aria-description attribute ---
        const ariaDescriptionAttr = el.getAttribute && el.getAttribute('aria-description');
        const ariaDescriptionText = normText(ariaDescriptionAttr);
        if (ariaDescriptionText) {
            addHelper(ariaDescriptionText, SOURCE_ARIA_DESCRIPTION, el);
        }

        // --- 0.5 aria-placeholder attribute ---
        const ariaPlaceholderAttr = el.getAttribute && el.getAttribute('aria-placeholder');
        const ariaPlaceholderText = normText(ariaPlaceholderAttr);
        if (ariaPlaceholderText) {
            addHelper(ariaPlaceholderText, SOURCE_ARIA_PLACEHOLDER, el);
        }

        // --- 1. aria-describedby ---
        const describedby = el.getAttribute && el.getAttribute('aria-describedby');
        const describedIds = new Set();

        if (describedby) {
            for (const id of describedby.split(/\s+/)) {
                if (!id) continue;
                describedIds.add(id);
            }

            const ariaParts = [];
            let firstNode = null;
            for (const id of describedIds) {
                const target = document.getElementById(id);
                if (!target) continue;

                // Skip obvious error messages
                const cls = (target.className || '').toString().toLowerCase();
                if (/error|invalid|validation|err/.test(cls)) continue;

                const t = normText(target.textContent);
                if (!t) continue;

                if (!firstNode) firstNode = target;
                ariaParts.push(t);
            }

            const ariaText = normText(ariaParts.join(' '));
            if (ariaText) {
                addHelper(ariaText, SOURCE_ARIA_DESCRIBEDBY, firstNode || el);
            }
        }

        // --- 2. title attribute (only if no aria-describedby text) ---
        const titleAttr = el.getAttribute && el.getAttribute('title');
        const titleText = normText(titleAttr);
        if (titleText && !isMostlyFromLabel(titleText.toLowerCase(), labelLower)) {
            addHelper(titleText, SOURCE_TITLE, el);
        }

        // --- 3. Placeholder used as helper (only if not used as label) ---
        const placeholderAttr = el.getAttribute && el.getAttribute('placeholder');
        const placeholderText = normText(placeholderAttr);
        if (!visualLabelIsPlaceholder 
            && placeholderText 
            && placeholderText.toLowerCase() !== labelLower
            && !isMostlyFromLabel(placeholderText.toLowerCase(), labelLower)
        ) {
            addHelper(placeholderText, SOURCE_PLACEHOLDER_ATTR, el);
        }

        // --- 3.5. CSS pseudo-element content (e.g. content: attr(data-placeholder)) ---
        const beforeContent = getPseudoContent('::before');
        if (beforeContent) {
            addHelper(beforeContent, SOURCE_CSS_PLACEHOLDER, el);
        }
        const afterContent = getPseudoContent('::after');
        if (afterContent) {
            addHelper(afterContent, SOURCE_CSS_PLACEHOLDER, el);
        }

        // --- 4. Supplementary/helper text nested inside the control's own label ---
        let foundInLabelSupplementaryHelper = false;
        const enclosingLabel = el.closest && el.closest('label');
        if (enclosingLabel) {
            const labelWalker = document.createTreeWalker(
                enclosingLabel,
                NodeFilter.SHOW_TEXT,
                {
                    acceptNode(node) {
                        if (!node || !node.parentElement) return NodeFilter.FILTER_REJECT;
                        if (el.contains(node.parentElement)) return NodeFilter.FILTER_REJECT;

                        const parent = node.parentElement;
                        const txt = normText(node.nodeValue);
                        if (!txt) return NodeFilter.FILTER_REJECT;
                        const txtLower = txt.toLowerCase();

                        if (!hasSupplementaryAncestorWithinLabel(parent)) {
                            return NodeFilter.FILTER_REJECT;
                        }

                        if (labelLower && isMostlyFromLabel(txtLower, labelLower)) {
                            return NodeFilter.FILTER_REJECT;
                        }

                        return NodeFilter.FILTER_ACCEPT;
                    }
                },
                false
            );

            while (labelWalker.nextNode()) {
                const node = labelWalker.currentNode;
                const txt = normText(node.nodeValue);
                if (!txt) continue;
                addHelper(txt, SOURCE_HELPER_NEARBY, node.parentElement || node);
                foundInLabelSupplementaryHelper = true;
            }
        }

        function isMeaningfulWrapper(node) {
            if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;

            const tagName = (node.tagName || '').toUpperCase();
            if (tagName === 'LABEL') {
                return false;
            }

            const role = (node.getAttribute && (node.getAttribute('role') || '')).toLowerCase();
            if (role === 'checkbox' || role === 'radio') {
                return false;
            }

            return true;
        }

        function findNearestMeaningfulWrapper(element) {
            const isCheckbox = !!(element && element.matches && element.matches('input[type="checkbox"], [role="checkbox"]'));
            const isRadio = !!(element && element.matches && element.matches('input[type="radio"], [role="radio"]'));
            const groupedSelector = isCheckbox
                ? 'input[type="checkbox"], [role="checkbox"]'
                : (isRadio ? 'input[type="radio"], [role="radio"]' : '');

            let current = element && element.parentElement;
            let fallback = null;
            let primaryGroupedWrapper = null;
            let semanticGroupWrapper = null;
            let groupedFieldWrapper = null;
            let primaryWrapper = null;
            let secondaryWrapper = null;
            while (current) {
                if (isMeaningfulWrapper(current)) {
                    if (current.matches && current.matches(PRIMARY_SEMANTIC_FIELD_WRAPPER_SELECTOR)) {
                        primaryWrapper = primaryWrapper || current;
                    }

                    if (current.matches && current.matches(SECONDARY_SEMANTIC_FIELD_WRAPPER_SELECTOR)) {
                        secondaryWrapper = secondaryWrapper || current;
                    }

                    if (current.matches && current.matches(FIELD_WRAPPER_SELECTOR)) {
                        fallback = fallback || current;

                        if (!groupedSelector) {
                            current = current.parentElement;
                            continue;
                        }

                        const groupedCount = current.querySelectorAll(groupedSelector).length;
                        if (groupedCount > 1) {
                            if (!groupedFieldWrapper) {
                                groupedFieldWrapper = current;
                            }

                            if (!primaryGroupedWrapper && current.matches(PRIMARY_SEMANTIC_FIELD_WRAPPER_SELECTOR)) {
                                primaryGroupedWrapper = current;
                            }
                        }
                    }

                    if (groupedSelector && !semanticGroupWrapper && current.matches && current.matches('fieldset, [role="group"], [role="radiogroup"]')) {
                        semanticGroupWrapper = current;
                    }
                }
                current = current.parentElement;
            }

            const hasGroupedWrapper = !!(primaryGroupedWrapper || semanticGroupWrapper || groupedFieldWrapper);

            if (!groupedSelector || !hasGroupedWrapper) {
                return primaryWrapper || secondaryWrapper || fallback || document.body;
            }

            return primaryGroupedWrapper || semanticGroupWrapper || groupedFieldWrapper || fallback || document.body;
        }

        // --- 5. Visual helper text nearby via TreeWalker ---
        // If the control already exposes supplementary text inside its own label,
        // prefer that local helper content over broader wrapper text.
        if (!foundInLabelSupplementaryHelper) {
            const wrapper = findNearestMeaningfulWrapper(el);

            const walker = document.createTreeWalker(
                wrapper,
                NodeFilter.SHOW_TEXT,
                {
                    acceptNode(node) {
                        if (!node || !node.parentElement) return NodeFilter.FILTER_REJECT;

                        // Don't treat text inside the control itself as helper text
                        if (el.contains(node.parentElement)) {
                            return NodeFilter.FILTER_REJECT;
                        }

                        // Skip nodes that belong to aria-describedby targets
                        const parent = node.parentElement;
                        if (parent.id && describedIds.has(parent.id)) {
                            return NodeFilter.FILTER_REJECT;
                        }

                        const parentTag = parent.tagName || '';
                        const parentCls = (parent.className || '').toString().toLowerCase();

                        // Skip style/script content
                        if (parentTag === 'STYLE' || parentTag === 'SCRIPT') {
                            return NodeFilter.FILTER_REJECT;
                        }

                        // Skip text that belongs to interactive widgets such as buttons/links.
                        if (parent.closest && parent.closest('button, [role="button"], a[href], summary')) {
                            return NodeFilter.FILTER_REJECT;
                        }

                        // Skip obvious labels (fallback), except supplementary/helper-like text nested inside a label.
                        if (parentTag === 'LEGEND') {
                            return NodeFilter.FILTER_REJECT;
                        }

                        const parentLabel = parent.closest && parent.closest('label');
                        if (parentTag === 'LABEL' || parentLabel) {
                            if (!hasSupplementaryAncestorWithinLabel(parent)) {
                                return NodeFilter.FILTER_REJECT;
                            }
                        }

                        // Skip obvious error messages
                        if (/error|invalid|validation|err/.test(parentCls)) {
                            return NodeFilter.FILTER_REJECT;
                        }

                        const txt = normText(node.nodeValue);
                        if (!txt) return NodeFilter.FILTER_REJECT;

                        const txtLower = txt.toLowerCase();

                        // Skip text that appears to be (mostly) the visual label itself,
                        // including small fragments like "*".
                        if (labelLower && isMostlyFromLabel(txtLower, labelLower)) {
                            return NodeFilter.FILTER_REJECT;
                        }

                        return NodeFilter.FILTER_ACCEPT;
                    }
                },
                false
            );

            while (walker.nextNode()) {
                const node = walker.currentNode;
                const txt = normText(node.nodeValue);
                if (!txt) continue;
                addHelper(txt, SOURCE_HELPER_NEARBY, node.parentElement || node);
            }
        }

        if (!helpers.length) {
            return [{ text: '', source: SOURCE_NONE }];
        }

        // Order helpers by the DOM position of their associated node
        const ordered = helpers.slice().sort((a, b) => {
            const na = a._node;
            const nb = b._node;
            if (!na || !nb || na === nb) return 0;
            try {
                const pos = na.compareDocumentPosition(nb);
                if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
                if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;
            } catch (e) {}
            return 0;
        });

        return ordered.map(({ _node, ...rest }) => rest);
    }, {
        FIELD_WRAPPER_SELECTOR,
        PRIMARY_SEMANTIC_FIELD_WRAPPER_SELECTOR,
        SECONDARY_SEMANTIC_FIELD_WRAPPER_SELECTOR,
        FALLBACK_FIELD_WRAPPER_SELECTOR,
        visualLabelText,
        SOURCE_HELPER_NEARBY,
        SOURCE_ARIA_DESCRIBEDBY,
        SOURCE_ARIA_DESCRIPTION,
        SOURCE_ARIA_PLACEHOLDER,
        SOURCE_PLACEHOLDER_ATTR,
        SOURCE_TITLE,
        SOURCE_CSS_PLACEHOLDER,
        SOURCE_NONE,
        visualLabelIsPlaceholder
    });

    return helper || '';
}

// Utility to combine helper text entries into a single string
// Accepts either a single helper object or an array of helpers
// Returns a space-normalized string of all helper texts
const combineHelperTexts = (helper) => {
    const helpers = Array.isArray(helper)
        ? helper
        : (helper ? [helper] : []);

    return helpers
        .map(h => (h && h.text) ? String(h.text) : '')
        .join(' ')
        .replace(/\s+/g, ' ')
        .trim();
};



// Return the Chromium accessibility-tree description for the given node.
const getAccessibleDescription = async (el) => {
    return getAccessibilityTreeDescription(el);
};

module.exports.getHelperText = getHelperText;
module.exports.SOURCE_HELPER_NEARBY = SOURCE_HELPER_NEARBY;
module.exports.SOURCE_ARIA_DESCRIBEDBY = SOURCE_ARIA_DESCRIBEDBY;
module.exports.SOURCE_ARIA_DESCRIPTION = SOURCE_ARIA_DESCRIPTION;
module.exports.SOURCE_ARIA_PLACEHOLDER = SOURCE_ARIA_PLACEHOLDER;
module.exports.SOURCE_PLACEHOLDER_ATTR = SOURCE_PLACEHOLDER_ATTR;
module.exports.SOURCE_TITLE = SOURCE_TITLE;
module.exports.SOURCE_CSS_PLACEHOLDER = SOURCE_CSS_PLACEHOLDER;
module.exports.SOURCE_NONE = SOURCE_NONE;
module.exports.combineHelperTexts = combineHelperTexts;
module.exports.getAccessibleDescription = getAccessibleDescription;
